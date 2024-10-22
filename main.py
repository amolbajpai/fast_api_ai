from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Book, Review, User, async_session, init_db
from llama3_model import generate_book_summary, recommend_books
from typing import List, Dict, Union, Optional
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from models import Genre, Role
import os

# FastAPI app instance
app = FastAPI()

# Security and hashing configurations
SECRET_KEY = os.getenv("SECRET_KEY")
if SECRET_KEY is None:
    raise ValueError("SECRET_KEY must be set in the environment variables.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class UserCreate(BaseModel):
    username: str
    password: str
    email: str
    interested_genre: Genre
    role: Role

    class Config:
        orm_mode = True



class UserSchema(BaseModel):
    id: int
    username: str
    email: str
    interested_genre: Genre
    role: Role

    class Config:
        orm_mode = True
        

class BookSchema(BaseModel):
    id: int
    title: str
    author: str
    genre: Genre
    year_published: int
    summary: str

class BookCreateSchema(BaseModel):
    title: str
    author: str
    genre: Genre
    year_published: int
    summary: Optional[str] = Field(default='')

    class Config:
        orm_mode = True

class ReviewSchema(BaseModel):
    book_id: int
    user_id: int
    review_text: str
    rating: int

class ReviewCreateSchema(BaseModel):
    review_text: str
    rating: int


class BookContent(BaseModel):
    book_content : str

# Dependency for DB session
async def get_db():
    async with async_session() as session:
        yield session

# Initialize the database
@app.on_event("startup")
async def on_startup():
    await init_db()


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Fetch the user from the database using the user_id
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar()

    if user is None:
        raise credentials_exception
    # Return the user (or user_id if you need just the ID)
    return user  # You can also return user.id if that's all you need

# New dependency to check if user is an admin
async def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access is required")

# Password utility functions
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Token creation utility
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# User registration endpoint
@app.post("/users", response_model=UserSchema)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    """
    User registration endpoint.

    This endpoint allows a new user to register by providing their username, email, password, 
    interested genre, and role. The system checks if the username or email already exists in the database. 
    If either is found, it raises an HTTP 400 error. If the user is successfully created, 
    it returns the new user's information.

    Args:
        user (UserCreate): The user data required for registration, including username, email, 
                           password, interested genre, and role.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If the username or email is already registered, an error with status code 400 
                       and a detailed message is raised.

    Returns:
        UserSchema: The newly created user object, including the hashed password and other user details.
    """
    # Check if the username or email already exists
    existing_user = await db.execute(select(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ))
    if existing_user.scalar() is not None:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        password=hashed_password,
        interested_genre=user.interested_genre,
        role=user.role
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


# User login endpoint
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)) -> dict:
    """
    User login endpoint.

    This endpoint allows users to log in by providing their username and password. 
    It verifies the credentials against the stored user data. If the username 
    does not exist or the password is incorrect, it raises an HTTP 400 error. 
    Upon successful login, it generates an access token for the user.

    Args:
        form_data (OAuth2PasswordRequestForm): The form data containing the user's 
                                                username and password. It is automatically 
                                                injected via dependency injection.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If the username does not exist or the password is incorrect, an error 
                       with status code 400 and a detailed message is raised.

    Returns:
        dict: A dictionary containing the access token and the token type, typically 'bearer'.
               The access token is used for authenticating future requests.
    """
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar()
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"user_id": user.id, "sub": user.username}, expires_delta=access_token_expires)

    return {"access_token": access_token, "token_type": "bearer"}

# To get current user
@app.get("/users/whoami", response_model=UserSchema)
async def whoami(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> UserSchema:
    """
    Get current user information.

    This endpoint retrieves the details of the currently authenticated user based on the 
    provided access token. It decodes the token to extract the username, checks the 
    validity of the token, and fetches the corresponding user from the database. If 
    the token is invalid or if the user does not exist, an HTTP 401 error is raised.

    Args:
        token (str): The Bearer token used for authentication. It is automatically 
                     provided via dependency injection from the OAuth2 scheme.
        db (AsyncSession, optional): The database session for performing database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If the credentials are invalid (either the token is not valid or the 
                       user does not exist), an error with status code 401 and a detailed 
                       message is raised.

    Returns:
        UserSchema: The details of the currently authenticated user, represented as an 
                     instance of the UserSchema.
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar()
    if user is None:
        raise credentials_exception
    return user

@app.post("/books", response_model=BookSchema, dependencies=[Depends(get_current_user)])
async def add_book(book: BookCreateSchema, db: AsyncSession = Depends(get_db)) -> Book:
    """
    Add a new book to the collection.

    This endpoint allows users to add a new book by providing the book's details such as title, author,
    and other relevant information. It first checks if a book with the same title and author already exists
    in the database. If it does, it raises an HTTP 400 error. Upon successful addition, it returns the newly 
    created book object.

    Args:
        book (BookCreateSchema): The schema containing the details of the book to be added.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If a book with the same title and author already exists, an error with 
                       status code 400 and a detailed message is raised.

    Returns:
        Book: The newly created book object.
    """
    # Check if the book with the same title and author already exists
    existing_book = await db.execute(select(Book).filter(
        (Book.title == book.title) & (Book.author == book.author)
    ))
    if existing_book.scalar() is not None:
        raise HTTPException(status_code=400, detail="Book with the same title and author already exists")

    # Create a new book
    new_book = Book(**book.model_dump())
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    return new_book


@app.put("/books/{id}", response_model=BookSchema, dependencies=[Depends(get_current_user)])
async def update_book(id: int, book: BookCreateSchema, db: AsyncSession = Depends(get_db)) -> Book:
    """
    Update an existing book's details.

    This endpoint allows users to update the information of a specific book by its ID. 
    It first fetches the book from the database; if the book does not exist, it raises a 
    404 error. If the book is found, it updates its attributes with the provided new data 
    and commits the changes to the database.

    Args:
        id (int): The ID of the book to be updated.
        book (BookCreateSchema): The schema containing the updated details of the book.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If the book with the given ID is not found, an error with status code 
                       404 and a detailed message is raised.

    Returns:
        Book: The updated book object.
    """
    # Fetch the book by ID
    existing_book = await db.get(Book, id)
    
    if not existing_book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Update the book with new data
    for key, value in book.model_dump().items():
        setattr(existing_book, key, value)

    # Save the changes to the database
    db.add(existing_book)
    await db.commit()
    await db.refresh(existing_book)
    
    return existing_book


@app.get("/books", response_model=List[BookSchema],dependencies=[Depends(get_current_user)])
async def get_books(db: AsyncSession = Depends(get_db)) -> List[BookSchema]:
    """
    Retrieve a list of all books.

    This endpoint fetches all the books from the database and returns them in a list. 
    It requires the user to be authenticated. The returned list contains details of each book, 
    structured according to the BookSchema.

    Args:
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Returns:
        List[BookSchema]: A list of books, each represented by the BookSchema.
    """
    result = await db.execute(select(Book))
    books = result.scalars().all()
    return books


@app.get("/books/{id}", response_model=BookSchema, dependencies=[Depends(get_current_user)])
async def get_book(id: int, db: AsyncSession = Depends(get_db)) -> Book:
    """
    Retrieve a specific book by its ID.

    This endpoint fetches the details of a book from the database using its unique ID. 
    If the book with the specified ID does not exist, it raises a 404 HTTP error.

    Args:
        id (int): The unique identifier of the book to be retrieved.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If no book with the specified ID is found, a 404 error is raised with a detailed message.

    Returns:
        BookSchema: The details of the book represented by the BookSchema.
    """
    result = await db.execute(select(Book).where(Book.id == id))
    book = result.scalar()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@app.delete("/books/{id}", response_model=BookSchema, dependencies=[Depends(get_current_user)])
async def delete_book(id: int, db: AsyncSession = Depends(get_db)) -> Book:
    """
    Delete a specific book by its ID.

    This endpoint removes a book from the database using its unique ID. 
    If the book with the specified ID does not exist, it raises a 404 HTTP error. 
    Upon successful deletion, it returns the details of the deleted book.

    Args:
        id (int): The unique identifier of the book to be deleted.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: If no book with the specified ID is found, a 404 error is raised with a detailed message.

    Returns:
        BookSchema: The details of the deleted book represented by the BookSchema.
    """
    # Fetch the book by ID
    existing_book = await db.get(Book, id)
    
    if not existing_book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Delete the book from the database
    await db.delete(existing_book)
    await db.commit()

    return existing_book


@app.post("/books/{id}/reviews", response_model=ReviewSchema)
async def add_review(
    id: int, 
    review: ReviewCreateSchema, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
    ) -> ReviewSchema:
    """
    Add a review for a specific book.

    This endpoint allows authenticated users to submit a review for a book identified by its ID. 
    It checks if the book exists and if the user has already submitted a review for that book. 
    If the book does not exist, a 404 error is raised. If the user has already reviewed the book, 
    a 400 error is raised. Upon successful review submission, it returns the details of the newly created review.

    Args:
        id (int): The unique identifier of the book to be reviewed.
        review (ReviewCreateSchema): The review data to be added, including the rating and comment.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.
        current_user (User, optional): The currently logged-in user, automatically injected.

    Raises:
        HTTPException: 
            - If no book with the specified ID is found, a 404 error is raised with a detailed message.
            - If the user has already reviewed the book, a 400 error is raised indicating that only one review is allowed.

    Returns:
        ReviewSchema: The details of the newly created review represented by the ReviewSchema.
    """
    # Check if the book exists
    result = await db.execute(select(Book).filter(Book.id == id))
    book = result.scalar()

    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Check if the user has already reviewed this book
    existing_review = await db.execute(
        select(Review).filter(Review.book_id == id, Review.user_id == current_user.id)
    )
    if existing_review.scalar() is not None:
        raise HTTPException(status_code=400, detail="You can only rate a book once.")

    # assign the user ID from the current logged-in user
    new_review = Review(user_id=current_user.id, book_id=id, **review.model_dump())
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)
    
    return new_review



@app.get("/books/{id}/reviews", response_model=List[ReviewSchema],dependencies=[Depends(get_current_user)])
async def get_reviews(id: int, db: AsyncSession = Depends(get_db)) -> List[ReviewSchema]:
    """
    Retrieve all reviews for a specific book.

    This endpoint allows authenticated users to fetch all reviews associated with a book identified by its ID. 
    It retrieves the reviews from the database and returns them in a list format. 
    If no reviews exist for the specified book, an empty list is returned.

    Args:
        id (int): The unique identifier of the book whose reviews are to be retrieved.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: 
            - If no book with the specified ID is found, a 404 error is raised with a detailed message. (This can be handled if desired, but is not implemented in this version.)

    Returns:
        List[ReviewSchema]: A list of reviews associated with the specified book, represented by the ReviewSchema. 
                            If no reviews exist, an empty list is returned.
    """
    result = await db.execute(select(Review).where(Review.book_id == id))
    reviews = result.scalars().all()
    return reviews

@app.get("/books/{book_id}/summary", dependencies=[Depends(get_current_user)])
async def get_book_summary(book_id: int, db: AsyncSession = Depends(get_db)) -> Dict[str, Union[str, float]]:
    """
    Retrieve the summary and average rating of a specific book.

    This endpoint allows authenticated users to fetch the summary and average rating of a book 
    identified by its ID. It retrieves the book's details from the database and calculates 
    the average rating based on its reviews. If no reviews exist, the average rating is marked as "NA".

    Args:
        book_id (int): The unique identifier of the book whose summary is to be retrieved.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException: 
            - If no book with the specified ID is found, a 404 error is raised with a detailed message.

    Returns:
        Dict: A dictionary containing the book summary and the average rating. 
                                       The average rating will be "NA" if no reviews are available.
    """
    # Fetch the book by ID
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar()

    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Fetch all reviews related to the book
    review_result = await db.execute(select(Review).where(Review.book_id == book_id))
    reviews = review_result.scalars().all()

    # Calculate the average rating if reviews exist
    if reviews:
        total_rating = sum(review.rating for review in reviews)
        average_rating = round(total_rating / len(reviews), 2)
    else:
        average_rating = "NA"

    # Return the summary and average rating
    return {
        "summary": book.summary,
        "average_rating": average_rating
    }


@app.post("/books/{id}/generate-summary", dependencies=[Depends(get_current_user),Depends(require_admin)])
async def generate_summary(id: int, book_content: BookContent, db: AsyncSession = Depends(get_db)) -> Dict[str, str]:
    """
    Generate a summary for a specific book based on provided content using LLM.

    This endpoint allows authenticated admin users to generate a summary for a book identified by its 
    ID. It retrieves the book from the database, uses the provided content along with the Llama3 model 
    to generate a summary, updates the book's summary in the database, and returns the updated summary.

    Args:
        id (int): The unique identifier of the book for which the summary is to be generated.
        book_content (BookContent): The content from which the summary is generated.
        db (AsyncSession, optional): The database session for performing the database operations. 
                                     It is automatically injected via dependency injection.

    Raises:
        HTTPException:
            - If no book with the specified ID is found, a 404 error is raised with a detailed message.
            - If the provided book content is too short to summarize, a 400 error is raised with a detailed message.

    Returns:
        Dict[str, str]: A dictionary containing the updated summary of the book generated by the LLM.
    """
    # Retrieve the book by its ID
    result = await db.execute(select(Book).where(Book.id == id))
    book = result.scalar()

    # If the book does not exist, raise an exception
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Generate the summary for the given content
    summary = await generate_book_summary(book,book_content)

    # Update the book's summary in the database
    book.summary = summary
    db.add(book)
    await db.commit()
    await db.refresh(book)

    # Return the updated summary
    return {"summary": book.summary}


@app.get("/recommendations", dependencies=[Depends(get_current_user)])
async def get_recommendations(current_user: User = Depends(get_current_user)):
    recommended_book = await recommend_books(current_user.interested_genre)
    return {"recommendations": recommended_book}