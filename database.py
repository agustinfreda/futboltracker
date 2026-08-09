import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. Definir la URL de la base de datos.
#    - En tu máquina (desarrollo local): no seteás DATABASE_URL, así que
#      cae al fallback de MySQL de siempre.
#    - En Render (producción): Render te da automáticamente la variable
#      de entorno DATABASE_URL apuntando a la base de Postgres que le
#      conectes al servicio. No hay que tocar nada más que la config
#      del servicio en el dashboard de Render.
SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "mysql+pymysql://root:untref_bbdd@localhost:3306/futbol_tracker",
)

# Render (y algunos otros hosts) todavía entregan la URL con el prefijo
# viejo "postgres://", que SQLAlchemy 1.4+ ya no acepta — hay que
# normalizarlo a "postgresql://". No afecta en nada al desarrollo local.
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Crear el engine de SQLAlchemy
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# 3. Crear la fábrica de sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Clase base para los modelos
Base = declarative_base()

# 5. Función generadora para abrir/cerrar sesión en cada endpoint
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()