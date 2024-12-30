import uuid
from datetime import datetime
from app.data import (
    store_chat_history, 
    retrieve_chat_history,  # Added function for retrieving chat history
    retrieve_relevant_texts
)
from app.vector_store import reload_vector_store_if_needed
from langchain_groq import ChatGroq
from langchain.chains import ConversationalRetrievalChain
from langchain_community.vectorstores import FAISS
from supabase import create_client
from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import threading
import logging

# Set up logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("Supabase URL and key are not set in the environment variables.")
    raise ValueError("Supabase URL and key are not set in the environment variables.")

# Initialize Supabase client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Chatbot configuration
SYSTEM_PROMPT = """You are an intelligent and helpful assistant specializing in providing detailed, accurate, and practical answers for queries related to the BDM project. Your role is to:
1. Guide users for the BDM project like formats of proposal, mid-term report, and final report. Page, font, line spacing settings.
2. Guide users in solving problems related to supply chain management, financial analysis, operational efficiency, and data-driven decision-making.
3. Provide concise yet comprehensive explanations, including relevant examples, where necessary.
4. If a user’s query is unclear, politely ask for clarification.
5. If the question is outside your expertise or related to specific project data you don't have, inform the user and suggest alternative approaches or resources.
6. Use a professional and approachable tone suitable for business and academic environments.
Always ensure that your answers are actionable, focused, and aligned with best practices in business analysis and decision modeling."""

# Global variable to cache the model
model = None
model_lock = threading.Lock()  # Lock to ensure thread-safe model loading

# Load the model (cached if already loaded)
def load_model():
    global model
    if model is None:
        try:
            with model_lock:  # Ensure that only one thread loads the model
                if model is None:  # Double-checked locking to ensure only one thread loads
                    model = ChatGroq(
                        temperature=0.8, 
                        model="llama3-8b-8192",
                        system_prompt=SYSTEM_PROMPT
                    )
                    logger.info("Model loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise e
    return model

# Initialize model and vector store
try:
    model = load_model()
    vector_store = reload_vector_store_if_needed()
    retrieval_chain = ConversationalRetrievalChain.from_llm(model, retriever=vector_store.as_retriever())
    logger.info("Vector store and retrieval chain initialized.")
except Exception as e:
    logger.error(f"Error initializing model or vector store: {e}")
    raise e

# Function to generate chatbot response
def generate_chatbot_response(user_message, chat_history):
    try:
        response = retrieval_chain.invoke({
            "question": user_message,
            "chat_history": chat_history
        })
        return response["answer"]
    except Exception as e:
        logger.error(f"Error generating chatbot response: {e}")
        return "Sorry, I encountered an error while processing your request."

# Function to start a new chat
def start_new_chat():
    chat_id = str(uuid.uuid4())
    logger.info(f"New chat session started with ID: {chat_id}")
    return chat_id

# Function to process user message and update chat history
def process_user_message(chat_id, user_message, chat_history):
    bot_response = generate_chatbot_response(user_message, chat_history)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chat_history.append({
        "timestamp": timestamp,
        "user_message": user_message,
        "bot_response": bot_response
    })

    # Limit chat history size to the most recent 50 messages
    chat_history = chat_history[-50:]

    try:
        store_chat_history(chat_id, chat_history)
        logger.info(f"Chat history updated for chat_id: {chat_id}")
    except Exception as e:
        logger.error(f"Error storing chat history for chat_id {chat_id}: {e}")

    return bot_response, chat_history

# Flask app initialization
app = Flask(__name__)

# Start new chat route
@app.route('/start_chat', methods=['GET'])
def start_chat():
    chat_id = start_new_chat()
    return jsonify({"chat_id": chat_id}), 200

# Chat route
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    chat_id = data.get("chat_id")
    user_message = data.get("user_message")
    
    if not chat_id or not user_message:
        logger.warning("chat_id or user_message is missing in request.")
        return jsonify({"error": "chat_id and user_message are required"}), 400

    try:
        # Retrieve existing chat history, ensuring the session exists
        chat_history = retrieve_chat_history(chat_id) or []
        if not chat_history:
            logger.warning(f"No chat history found for chat_id: {chat_id}. Starting a new session.")
        
        bot_response, updated_chat_history = process_user_message(chat_id, user_message, chat_history)
        return jsonify({
            "bot_response": bot_response,
            "chat_history": updated_chat_history
        }), 200
    except Exception as e:
        logger.error(f"Error in chat route: {e}")
        return jsonify({"error": "An error occurred while processing your request."}), 500

# Main entry point
if __name__ == "__main__":
    app.run(debug=True)
