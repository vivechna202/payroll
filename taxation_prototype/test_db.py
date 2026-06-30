from database.engine import engine
from database.base import Base
import models.employee  # IMPORTANT: loads model

Base.metadata.create_all(bind=engine)

print("Tables created successfully")