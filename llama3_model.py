from llama_cpp import Llama
import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

# Load environment variables from .env file
load_dotenv()

# Set the Groq API key from environment variables
os.environ['GROQ_API_KEY'] = os.getenv("GROQ_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")

# Initialize the ChatGroq instance
llm = ChatGroq(model="Gemma2-9b-It", groq_api_key=groq_api_key)

# Function to generate a book summary using Llama3
async def generate_book_summary(book_content):
    messages = [
        SystemMessage(content="Summarize the book content in 100 words"),
        HumanMessage(content=f"{book_content}")
    ]
    
    # Invoke the Llama3 model for book summary generation
    result = llm.invoke(messages)
    return result.content

# Function to generate a review summary using Llama3
async def generate_review_summary(review_text):
    messages = [
        SystemMessage(content="Summarize this review"),
        HumanMessage(content=f"{review_text}")
    ]

    # Invoke the Llama3 model for review summary generation
    result = llm.invoke(messages)
    return result.content

