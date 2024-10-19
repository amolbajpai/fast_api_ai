from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Book, Review, User, async_session, init_db
from llama3_model import generate_book_summary, generate_review_summary
from pydantic import BaseModel
from typing import List
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta

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
class UserCreate(BaseModel):
    username: str
    password: str
    email: str

class UserSchema(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        orm_mode = True

class BookSchema(BaseModel):
    id: int
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

# Dependency for DB session
async def get_db():
    async with async_session() as session:
        yield session

# Initialize the database
@app.on_event("startup")
async def on_startup():
    await init_db()


# Dependency to verify JWT token
async def get_current_user(token: str = Depends(oauth2_scheme)):
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
    new_user = User(username=user.username, email=user.email, password=hashed_password)
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
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
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
async def add_book(book: BookSchema, db: AsyncSession = Depends(get_db)):
    new_book = Book(**book.dict())
    db.add(new_book)
    await db.commit()
    return new_book

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
@app.post("/books/{id}/reviews", response_model=ReviewSchema)
async def add_review(id: int, review: ReviewSchema, db: AsyncSession = Depends(get_db)):
    new_review = Review(book_id=id, **review.dict())
    db.add(new_review)
    await db.commit()
    return new_review

# GET /books/<id>/reviews: Retrieve all reviews for a book
@app.get("/books/{id}/reviews", response_model=List[ReviewSchema])
async def get_reviews(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Review).where(Review.book_id == id))
    reviews = result.scalars().all()
    return reviews

# GET /books/<id>/summary: Get a summary for a book
@app.get("/books/{id}/summary")
async def get_summary(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == id))
    book = result.scalar()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    summary = await generate_book_summary(book.summary)
    return {"summary": summary}

# POST /generate-summary: Generate a summary for a given book content
@app.post("/generate-summary")
async def generate_summary(content: str):
    summary = await generate_book_summary(content)
    return {"summary": summary}

# GET /recommendations: Get book recommendations based on user preferences
@app.get("/recommendations")
async def get_recommendations():
    # Implement recommendation logic here
    return {"recommendations": []}
