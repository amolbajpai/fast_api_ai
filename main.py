from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Book, Review, User, async_session, init_db
from llama3_model import generate_book_summary, generate_review_summary, recommend_books
from typing import List
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from pydantic import BaseModel, constr, validator
from models import Genre, Role

# FastAPI app instance
app = FastAPI()

# Security and hashing configurations
SECRET_KEY = "your_secret_key"  # Change this to a secure key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Pydantic Schemas
# class UserCreate(BaseModel):
#     username: str
#     password: str
#     email: str

class UserCreate(BaseModel):
    username: str
    password: str
    email: str
    interested_genre: Genre  # Single choice for genre
    role: Role

    class Config:
        orm_mode = True



class UserSchema(BaseModel):
    id: int
    username: str
    email: str
    interested_genre: Genre  # Single choice for genre
    role: Role

    class Config:
        orm_mode = True
        

class BookSchema(BaseModel):
    id: int
    title: str
    author: str
    genre: str
    year_published: int
    summary: str = None

class BookCreateSchema(BaseModel):
    title: str
    author: str
    genre: str
    year_published: int
    summary: str = None

class ReviewSchema(BaseModel):
    book_id: int
    user_id: int
    review_text: str
    rating: float

class ReviewCreateSchema(BaseModel):
    review_text: str
    rating: float


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


# # Dependency to verify JWT token
# async def get_current_user(token: str = Depends(oauth2_scheme)):
#     credentials_exception = HTTPException(
#         status_code=401,
#         detail="Could not validate credentials",
#         headers={"WWW-Authenticate": "Bearer"},
#     )
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         username: str = payload.get("sub")
#         if username is None:
#             raise credentials_exception
#     except JWTError:
#         raise credentials_exception

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")  # Assuming 'user_id' is stored in the JWT payload
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Fetch the user from the database using the user_id
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

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
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, email=user.email, password=hashed_password, interested_genre=user.interested_genre,role=user.role)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

# User login endpoint
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar()
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    access_token = create_access_token(data={"user_id": user.id, "sub": user.username}, expires_delta=access_token_expires)

    return {"access_token": access_token, "token_type": "bearer"}

# Protected route to get current user
@app.get("/users/me", response_model=UserSchema)
async def read_users_me(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
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

# Other book and review endpoints remain unchanged...
# POST /books: Add a new book
@app.post("/books", response_model=BookSchema)
async def add_book(book: BookCreateSchema, db: AsyncSession = Depends(get_db)):
    new_book = Book(**book.dict())
    db.add(new_book)
    await db.commit()
    return new_book


@app.put("/books/{id}", response_model=BookSchema)
async def update_book(id: int, book: BookCreateSchema, db: AsyncSession = Depends(get_db)):
    # Fetch the book by ID
    existing_book = await db.get(Book, id)
    
    if not existing_book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Update the book with new data
    for key, value in book.dict().items():
        setattr(existing_book, key, value)

    # Save the changes to the database
    db.add(existing_book)
    await db.commit()
    await db.refresh(existing_book)
    
    return existing_book


# GET /books: Retrieve all books
@app.get("/books", response_model=List[BookSchema],dependencies=[Depends(get_current_user)])
async def get_books(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book))
    books = result.scalars().all()
    return books

# GET /books/<id>: Retrieve a specific book
@app.get("/books/{id}", response_model=BookSchema, dependencies=[Depends(get_current_user)])
async def get_book(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == id))
    book = result.scalar()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book

# POST /books/<id>/reviews: Add a review
# @app.post("/books/{id}/reviews", response_model=ReviewSchema)
# async def add_review(id: int, review: ReviewCreateSchema, db: AsyncSession = Depends(get_db), user_id:int = get_current_user):
#     new_review = Review(user_id=user_id, **review.dict())
#     db.add(new_review)
#     await db.commit()
#     return new_review

@app.delete("/books/{id}", response_model=BookSchema)
async def delete_book(id: int, db: AsyncSession = Depends(get_db)):
    # Fetch the book by ID
    existing_book = await db.get(Book, id)
    
    if not existing_book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Delete the book from the database
    await db.delete(existing_book)
    await db.commit()

    return existing_book  # Optionally return the deleted book's info


@app.post("/books/{id}/reviews", response_model=ReviewSchema, dependencies=[Depends(get_current_user)])
async def add_review(
    id: int, 
    review: ReviewCreateSchema, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = Depends(get_current_user)
    ):
    # Check if the book exists
    result = await db.execute(select(Book).filter(Book.id == id))
    book = result.scalar_one_or_none()

    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    # Check if the user has already reviewed this book
    existing_review = await db.execute(
        select(Review).filter(Review.book_id == id, Review.user_id == current_user.id)
    )
    if existing_review.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="You can only rate a book once.")

    # Automatically assign the user ID from the current logged-in user
    new_review = Review(user_id=current_user.id, book_id=id, **review.dict())
    db.add(new_review)
    await db.commit()
    await db.refresh(new_review)
    
    return new_review



# GET /books/<id>/reviews: Retrieve all reviews for a book
@app.get("/books/{id}/reviews", response_model=List[ReviewSchema],dependencies=[Depends(get_current_user)])
async def get_reviews(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Review).where(Review.book_id == id))
    reviews = result.scalars().all()
    return reviews

# GET /books/<id>/summary: Get a summary for a book
@app.get("/books/{book_id}/summary", dependencies=[Depends(get_current_user)])
async def get_book_summary(book_id: int, db: AsyncSession = Depends(get_db)):
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

# # POST /generate-summary: Generate a summary for a given book content
# @app.post("/books/{id}/generate-summary",dependencies=[Depends(get_current_user)])
# async def generate_summary(id: int, content: str, dependencies=[Depends(get_current_user)]):
#     summary = await generate_book_summary(content)
#     return {"summary": summary}

@app.post("/books/{id}/generate-summary", dependencies=[Depends(get_current_user),Depends(require_admin)])
async def generate_summary(id: int, book_content: BookContent, db: AsyncSession = Depends(get_db)):
    # Retrieve the book by its ID
    result = await db.execute(select(Book).where(Book.id == id))
    book = result.scalar_one_or_none()

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


# GET /recommendations: Get book recommendations based on user preferences
@app.get("/recommendations", dependencies=[Depends(get_current_user)])
async def get_recommendations(current_user: User = Depends(get_current_user)):
    # Fetch the user from the database using the user_id
    # user = await db.execute(select(User).filter(User.id == user_id))
    recommended_book = await recommend_books(current_user.interested_genre)
    return {"recommendations": recommended_book}