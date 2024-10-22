from llama_cpp import Llama
from fastapi import HTTPException
import os
import re
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
import asyncio

# Load environment variables from .env file
load_dotenv()

# Set the Groq API key from environment variables
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("GROQ_API_KEY must be set in the environment variables.")
os.environ['GROQ_API_KEY'] = groq_api_key

# Initialize the ChatGroq instance
llm = ChatGroq(model="llama-3.2-90b-text-preview")

# Asynchronous function to invoke LLM
async def invoke_llm(messages):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, llm.invoke, messages)

# Function to generate a book summary using Llama3
async def generate_book_summary(book, book_content):
    messages = [
        SystemMessage(content="""Summarize the following book in 70 to 100 words: Title, Author, Publish Year, Genre, and book content are provided. 
                                Generate a summary based solely on the provided content; do not use any prior knowledge. 
                                Avoid including unrelated information. 
                                Don't add sentences like 'Here is a 70-100 word summary of the book'
                                Stick to the given instructions.
                                If the Book Content is too short to summarize, return "NONE"."""),
        HumanMessage(content=f"Title: {book.title}, Author: {book.author}, Publish Year: {book.year_published}, Genre: {book.genre}, Book Content: {book_content}")
    ]

    # Invoke the Llama3 model for book summary generation
    result = await invoke_llm(messages)
    if "NONE" in result.content:
        raise HTTPException(status_code=400, detail="Please provide enough book content to generate a summary.")

    return result.content

# Function to generate a review summary using Llama3
async def generate_review_summary(review_text):
    messages = [
        SystemMessage(content="Provide a concise summary of the main points and sentiments expressed in the review."),
        HumanMessage(content=f"{review_text}")
    ]

    # Invoke the Llama3 model for review summary generation
    result = await invoke_llm(messages)
    return result.content

# Function to recommend books based on user's interested genre
async def recommend_books(interested_genre):
    messages = [
        SystemMessage(content="""Recommend books to the user based on their interest; only provide a list of 10 books separated by ';'.
                                Ensure there are no extra spaces or non-printable characters in the output.
                                Example:
                                    Sapiens: A Brief History of Humankind; The History of the Ancient World; The Guns of August 
                                    ; A People's History of the United States; The Wright Brothers; The Diary of a Young Girl 
                                    ; Team of Rivals: The Political Genius of Abraham Lincoln; The Silk Roads: A New History of the World 
                                    ; The Immortal Life of Henrietta Lacks; The Splendid and the Vile"""),
        HumanMessage(content=f"User is interested in {interested_genre} genre.")
    ]

    # Invoke the Llama3 model for book recommendations
    result = await invoke_llm(messages)
    result = re.sub(r'[\s]+', ' ', result.content)
    return [title.strip() for title in result.split(';')] 
