import os
import sys
import sqlite3
import re
from datetime import datetime

# ==========================================
# TRADUCTOR INTELIGENTE SQL SERVER -> SQLITE
# ==========================================
def clean_sql_for_sqlite(sql):
    if not isinstance(sql, str):
        return sql
    
    # 1. VARCHAR(MAX) y NVARCHAR(MAX) -> TEXT
    sql = re.sub(r'VARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'NVARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    
    # 2. DATEDIFF(day, ...) -> DATEDIFF('day', ...)
    sql = re.sub(r'\bDATEDIFF\s*\(\s*([a-zA-Z]+)\s*,', r"DATEDIFF('\1',", sql, flags=re.IGNORECASE)

    # 3. Subconsultas (SELECT TOP N ... FROM ...) -> (SELECT ... FROM ... LIMIT N)
    sql = re.sub(
        r'\(\s*SELECT\s+TOP\s+(\d+)\s+([^)]+)\)',
        lambda m: f"(SELECT {m.group(2)} LIMIT {m.group(1)})",
        sql,
        flags=re.IGNORECASE
    )
    
    # 4. Consultas principales SELECT TOP N ... -> SELECT ... LIMIT N
    match = re.search(r'^\s*SELECT\s+TOP\s+(\d+)\s+(.+)', sql, flags=re.IGNORECASE | re.DOTALL)
    if match and not re.search(r'\bLIMIT\b', match.group(2), flags=re.IGNORECASE):
        sql = f"SELECT {match.group(2)} LIMIT {match.group(1)}"
        
    return sql

# ==========================================
# CONVERSOR AUTOMÁTICO DE FECHAS A DATETIME
# ==========================================
def parse_date_if_str(val):
    if isinstance(val, str) and len(val) >= 10:
        if val[4] == '-' and val[7] == '-' and val[:4].isdigit() and val[5:7].isdigit() and val[8:10].isdigit():
            val_clean = val[:19]
            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    return datetime.strptime(val_clean, fmt)
                except ValueError:
                    pass
    return val

def normalize_key(k):
    return k.lower().replace('_', '') if isinstance(k, str) else k

class UniversalRow(dict):
    def __init__(self, cursor, row):
        super().__init__()
        self._keys = [col[0] for col in cursor.description]
        # Convierte cadenas de fecha a objetos datetime reales para soportar .strftime()
        self._row = [parse_date_if_str(val) for val in row]
        for idx, col in enumerate(self._keys):
            val = self._row[idx]
            self[col] = val
            self[normalize_key(col)] = val

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        if key in self:
            return super().__getitem__(key)
        norm = normalize_key(key)
        if norm in self:
            return super().__getitem__(norm)
        return None

    def __getattr__(self, item):
        val = self[item]
        if val is not None:
            return val
        raise AttributeError(f"No existe el atributo '{item}'")

    def get(self, key, default=None):
        val = self[key]
        return val if val is not None else default

class CompatCursor:
    def __init__(self, cur):
        self._cur = cur
        self._inserted_id = None

    def execute(self, sql, params=()):
        self._inserted_id = None
        has_output = bool(re.search(r'OUTPUT\s+INSERTED\.\w+', sql, flags=re.IGNORECASE))
        if has_output:
            sql = re.sub(r'OUTPUT\s+INSERTED\.\w+', '', sql, flags=re.IGNORECASE)
        
        sql_clean = clean_sql_for_sqlite(sql)
        res = self._cur.execute(sql_clean, params)
        if has_output:
            self._inserted_id = (self._cur.lastrowid,)
        return res

    def executemany(self, sql, seq):
        sql_clean = clean_sql_for_sqlite(sql)
        return self._cur.executemany(sql_clean, seq)

    def fetchone(self):
        if self._inserted_id is not None:
            val = self._inserted_id
            self._inserted_id = None
            return val
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)

class CompatConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return CompatCursor(self._conn.cursor())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

# ==========================================
# FUNCIONES SQL VIRTUALES
# ==========================================
def sqlite_datediff(unit, d1, d2):
    if not d1 or not d2:
        return 0
    def parse_dt(d):
        if isinstance(d, datetime):
            return d
        d_str = str(d)[:19]
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d'):
            try:
                return datetime.strptime(d_str, fmt)
            except ValueError:
                pass
        return datetime.now()
    t1 = parse_dt(d1)
    t2 = parse_dt(d2)
    return int((t2.date() - t1.date()).days)

# ==========================================
# AUTO-RELLENO DE BASE DE DATOS (NUBE)
# ==========================================
DB_SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'biblioteca_cloud.db')

def seed_cloud_database(conn):
    cur = conn.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS Carreras (
        carrera_id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        codigo TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Usuarios (
        usuario_id INTEGER PRIMARY KEY AUTOINCREMENT,
        dni TEXT UNIQUE NOT NULL,
        nombres TEXT NOT NULL,
        apellidos TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'ALUMNO',
        carrera_id INTEGER,
        ciclo INTEGER DEFAULT 1,
        estado TEXT DEFAULT 'ACTIVO',
        FOREIGN KEY (carrera_id) REFERENCES Carreras(carrera_id)
    );

    CREATE TABLE IF NOT EXISTS Libros (
        libro_id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        autor TEXT NOT NULL,
        editorial TEXT,
        anio_publicacion INTEGER,
        isbn TEXT,
        tipo_recurso TEXT DEFAULT 'HIBRIDO',
        archivo_pdf_url TEXT,
        descripcion TEXT
    );

    CREATE TABLE IF NOT EXISTS LibroCarrera (
        libro_id INTEGER NOT NULL,
        carrera_id INTEGER NOT NULL,
        PRIMARY KEY (libro_id, carrera_id)
    );

    CREATE TABLE IF NOT EXISTS Ejemplares (
        ejemplar_id INTEGER PRIMARY KEY AUTOINCREMENT,
        libro_id INTEGER NOT NULL,
        codigo_patrimonio TEXT UNIQUE NOT NULL,
        estado_fisico TEXT DEFAULT 'DISPONIBLE',
        ubicacion_estante TEXT DEFAULT 'Estante 1-A'
    );

    CREATE TABLE IF NOT EXISTS Prestamos (
        prestamo_id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        ejemplar_id INTEGER NOT NULL,
        fecha_prestamo TEXT NOT NULL,
        fecha_devolucion_prevista TEXT NOT NULL,
        fecha_devolucion_real TEXT,
        estado TEXT DEFAULT 'ACTIVO',
        carnet_custodia INTEGER DEFAULT 1,
        observaciones TEXT
    );

    CREATE TABLE IF NOT EXISTS AccesosDigitales (
        acceso_id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        libro_id INTEGER NOT NULL,
        fecha_acceso TEXT NOT NULL,
        direccion_ip TEXT DEFAULT '127.0.0.1'
    );
    ''')

    # Carreras
    cur.execute("SELECT COUNT(*) FROM Carreras")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO Carreras (carrera_id, nombre, codigo) VALUES (?, ?, ?)", [
            (1, 'Arquitectura de Plataformas y TI (APSTI)', 'APSTI'),
            (2, 'Enfermería Técnica', 'ENF'),
            (3, 'Producción Agropecuaria', 'AGRO'),
            (4, 'Contabilidad', 'CONT')
        ])

    # Usuarios
    cur.execute("SELECT COUNT(*) FROM Usuarios WHERE dni = 'admin'")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO Usuarios (dni, nombres, apellidos, password_hash, rol, carrera_id, ciclo, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ('admin', 'Administrador', 'Biblioteca Central', 'admin123', 'ADMIN', 1, 6, 'ACTIVO'),
            ('74859612', 'Marlo', 'Vilchez Cuzque', '74859612', 'ALUMNO', 1, 6, 'ACTIVO'),
            ('71234567', 'Rosa María', 'Díaz López', '71234567', 'ALUMNO', 2, 4, 'ACTIVO'),
            ('72345678', 'Juan Carlos', 'Huamán Quispe', '72345678', 'ALUMNO', 3, 2, 'ACTIVO'),
            ('73456789', 'Ana Lucía', 'Pérez Torres', '73456789', 'ALUMNO', 4, 5, 'ACTIVO')
        ])

    # Libros
    cur.execute("SELECT COUNT(*) FROM Libros")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO Libros (libro_id, titulo, autor, editorial, anio_publicacion, tipo_recurso, archivo_pdf_url, descripcion) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, 'Redes y Conectividad de Datos', 'Andrew S. Tanenbaum', 'Pearson', 2021, 'HIBRIDO', 'redes_datos.pdf', 'Topologías, protocolos TCP/IP y diseño de redes corporativas.'),
            (2, 'Desarrollo Web con Python y Flask', 'Miguel Grinberg', 'O Reilly', 2023, 'HIBRIDO', 'python_flask.pdf', 'Arquitectura MVC, APIs REST y plantillas Jinja2.'),
            (3, 'Manual de Primeros Auxilios y Soporte Básico', 'Cruz Roja Internacional', 'Médica Panamericana', 2022, 'HIBRIDO', 'primeros_auxilios.pdf', 'Protocolos de atención inicial y evaluación de signos vitales.'),
            (4, 'Farmacología Básica y Clínica', 'Bertram G. Katzung', 'McGraw-Hill', 2021, 'FISICO', None, 'Clasificación de fármacos, dosis terapéuticas y farmacovigilancia.'),
            (5, 'Manejo Agroecológico de Suelos y Cultivos', 'Miguel A. Altieri', 'Mundiprensa', 2022, 'HIBRIDO', 'manejo_suelos.pdf', 'Fertilidad del suelo, rotación de cultivos y control biológico.'),
            (6, 'Contabilidad Financiera y Tributaria', 'Erick Valdivia', 'Instituto Pacífico', 2023, 'HIBRIDO', 'contabilidad_tributaria.pdf', 'Normas NIIF, asientos contables y obligaciones fiscales Sunat.')
        ])

    # LibroCarrera
    cur.execute("SELECT COUNT(*) FROM LibroCarrera")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO LibroCarrera (libro_id, carrera_id) VALUES (?, ?)", [
            (1, 1),
            (2, 1),
            (3, 2),
            (4, 2),
            (5, 3),
            (6, 4)
        ])

    # Ejemplares
    cur.execute("SELECT COUNT(*) FROM Ejemplares")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO Ejemplares (libro_id, codigo_patrimonio, estado_fisico, ubicacion_estante) VALUES (?, ?, ?, ?)", [
            (1, 'APSTI-001-A', 'DISPONIBLE', 'Estante 1-A'),
            (1, 'APSTI-001-B', 'DISPONIBLE', 'Estante 1-A'),
            (2, 'APSTI-002-A', 'DISPONIBLE', 'Estante 1-B'),
            (3, 'ENF-001-A', 'DISPONIBLE', 'Estante 2-A'),
            (4, 'ENF-002-A', 'DISPONIBLE', 'Estante 2-B'),
            (5, 'AGRO-001-A', 'DISPONIBLE', 'Estante 3-A'),
            (6, 'CONT-001-A', 'DISPONIBLE', 'Estante 4-A')
        ])

    # Préstamos de prueba
    cur.execute("SELECT COUNT(*) FROM Prestamos")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO Prestamos (usuario_id, ejemplar_id, fecha_prestamo, fecha_devolucion_prevista, estado, carnet_custodia, observaciones)
            VALUES (2, 2, '2026-10-25 09:30:00', '2026-11-01 18:00:00', 'ACTIVO', 1, 'Carnet físico en custodia.')
        """)

    conn.commit()

# ==========================================
# CONEXIÓN PRINCIPAL
# ==========================================
def get_db_connection():
    if sys.platform.startswith('win'):
        try:
            import pyodbc
            conn_str = (
                "DRIVER={ODBC Driver 17 for SQL Server};"
                "SERVER=EQUIPO;"
                "DATABASE=BibliotecaUtcubamba;"
                "Trusted_Connection=yes;"
            )
            return pyodbc.connect(conn_str)
        except Exception:
            pass

    conn = sqlite3.connect(DB_SQLITE_PATH, check_same_thread=False)
    conn.row_factory = UniversalRow
    conn.create_function("GETDATE", 0, lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    conn.create_function("DATEDIFF", 3, sqlite_datediff)
    conn.create_function("ISNULL", 2, lambda a, b: b if a is None else a)
    seed_cloud_database(conn)
    return CompatConnection(conn)

def get_connection():
    return get_db_connection()

def get_db():
    return get_db_connection()
