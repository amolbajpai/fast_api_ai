from llama_cpp import Llama
from fastapi import HTTPException
import os
import re
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

# Load environment variables from .env file
load_dotenv()

# Set the Groq API key from environment variables
os.environ['GROQ_API_KEY'] = os.getenv("GROQ_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")

# Initialize the ChatGroq instance
llm = ChatGroq(model="llama-3.2-90b-text-preview", groq_api_key=groq_api_key) # Gemma2-9b-It    

# Function to generate a book summary using Llama3
async def generate_book_summary(book,book_content):

    messages = [
            SystemMessage(content="""Summarize the following book in 100 words: Title, Author, Publish Year, Genre and book content are provided. \
                                just generate summary of the book on the basis of the given content only, don't use your prior knowladge database\
                                    don't say that 'The provided content does not match the book title' or 'book content seems unrelated to the title'\
                                
                                In response, don't mention any out-of-context text.\
                                    if Book Content is very sort to summarize the book then return "NONE" in response"""),
            HumanMessage(content=f"Title: {book.title}, Author: {book.author}, Publish Year: {book.year_published}, Genre: {book.genre}, Book Content {book_content}")
        ]

    
    
    # Invoke the Llama3 model for book summary generation
    result = llm.invoke(messages)
    if "NONE" in result.content:
        raise HTTPException(status_code=400, detail="Please provide enough book content to generate summary")

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

# Function to generate a review summary using Llama3
async def recommend_books(interested_genre):
    messages = [
        SystemMessage(content="""Recommend books to the user based on their interest; only provide a list of 10 books separated by ';'.\
            Don't add extra space and or anyother non printable characters like \n
            Example:
                Sapiens: A Brief History of Humankind;The History of the Ancient World;The Guns of August 
                ;A People's History of the United States;The Wright Brothers;The Diary of a Young Girl 
                ;Team of Rivals: The Political Genius of Abraham Lincoln;The Silk Roads: A New History of the World 
                ;The Immortal Life of Henrietta Lacks;The Splendid and the Vile"""),
        HumanMessage(content=f"User is interested in {interested_genre} genre.")
    ]

    # Invoke the Llama3 model for review summary generation
    result = llm.invoke(messages)
    result = re.sub(r'[\s]+', ' ', result.content)
    return result.split(';')