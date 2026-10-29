import os
import sys
import sqlite3
import re
from datetime import datetime

# ==========================================
# GESTOR DE FILAS COMPATIBLE (SQL Server & SQLite)
# ==========================================
def normalize_key(k):
    return k.lower().replace('_', '') if isinstance(k, str) else k

ALIASES = {
    'idusuario': 'usuarioid',
    'idlibro': 'libroid',
    'idejemplar': 'ejemplarid',
    'idprestamo': 'prestamoid',
    'idcarrera': 'carreraid',
    'codigoejemplar': 'codigopatrimonio',
    'estado': 'estadofisico',
    'ubicacion': 'ubicacionestante',
    'clave': 'passwordhash',
    'password': 'passwordhash',
    'pdfurl': 'archivopdfurl',
    'archivodigital': 'archivopdfurl'
}

class UniversalRow(dict):
    def __init__(self, cursor, row):
        super().__init__()
        self._keys = [col[0] for col in cursor.description]
        self._row = row
        for idx, col in enumerate(self._keys):
            val = row[idx]
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
        alias = ALIASES.get(norm)
        if alias and alias in self:
            return super().__getitem__(alias)
        for k, v in ALIASES.items():
            if v == norm and k in self:
                return super().__getitem__(k)
        return None

    def __getattr__(self, item):
        val = self[item]
        if val is not None:
            return val
        raise AttributeError(f"No existe el atributo '{item}'")

    def get(self, key, default=None):
        val = self[key]
        return val if val is not None else default

# ==========================================
# TRADUCTOR DE CONSULTAS SQL
# ==========================================
class CompatCursor:
    def __init__(self, real_cursor):
        self._cur = real_cursor

    def execute(self, sql, params=()):
        # Traduce SELECT TOP N a LIMIT N para compatibilidad total
        match = re.search(r'SELECT\s+TOP\s+(\d+)\s+(.+)', sql, flags=re.IGNORECASE | re.DOTALL)
        if match:
            limit_num = match.group(1)
            rest = match.group(2)
            if not re.search(r'\bLIMIT\b', rest, flags=re.IGNORECASE):
                sql = f"SELECT {rest} LIMIT {limit_num}"
        return self._cur.execute(sql, params)

    def executemany(self, sql, seq):
        return self._cur.executemany(sql, seq)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

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
# FUNCIONES SQL PERSONALIZADAS
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
# INICIALIZACIÓN DE DATOS (NUBE / RENDER)
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
        descripcion TEXT,
        carrera_id INTEGER,
        FOREIGN KEY (carrera_id) REFERENCES Carreras(carrera_id)
    );

    CREATE TABLE IF NOT EXISTS Ejemplares (
        ejemplar_id INTEGER PRIMARY KEY AUTOINCREMENT,
        libro_id INTEGER NOT NULL,
        codigo_patrimonio TEXT UNIQUE NOT NULL,
        estado_fisico TEXT DEFAULT 'DISPONIBLE',
        ubicacion_estante TEXT DEFAULT 'Estante 1-A',
        FOREIGN KEY (libro_id) REFERENCES Libros(libro_id)
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
        observaciones TEXT,
        FOREIGN KEY (usuario_id) REFERENCES Usuarios(usuario_id),
        FOREIGN KEY (ejemplar_id) REFERENCES Ejemplares(ejemplar_id)
    );

    CREATE TABLE IF NOT EXISTS AccesosDigitales (
        acceso_id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        libro_id INTEGER NOT NULL,
        fecha_acceso TEXT NOT NULL,
        direccion_ip TEXT DEFAULT '127.0.0.1',
        FOREIGN KEY (usuario_id) REFERENCES Usuarios(usuario_id),
        FOREIGN KEY (libro_id) REFERENCES Libros(libro_id)
    );
    ''')

    cur.execute("SELECT COUNT(*) FROM Carreras")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO Carreras (carrera_id, nombre, codigo) VALUES (?, ?, ?)", [
            (1, 'Arquitectura de Plataformas y TI (APSTI)', 'APSTI'),
            (2, 'Enfermería Técnica', 'ENF'),
            (3, 'Producción Agropecuaria', 'AGRO'),
            (4, 'Contabilidad', 'CONT')
        ])

        cur.executemany("INSERT INTO Usuarios (dni, nombres, apellidos, password_hash, rol, carrera_id, ciclo, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            ('admin', 'Administrador', 'Biblioteca Central', 'admin123', 'ADMIN', 1, 6, 'ACTIVO'),
            ('74859612', 'Marlo', 'Vilchez Cuzque', '74859612', 'ALUMNO', 1, 6, 'ACTIVO'),
            ('71234567', 'Rosa María', 'Díaz López', '71234567', 'ALUMNO', 2, 4, 'ACTIVO'),
            ('72345678', 'Juan Carlos', 'Huamán Quispe', '72345678', 'ALUMNO', 3, 2, 'ACTIVO'),
            ('73456789', 'Ana Lucía', 'Pérez Torres', '73456789', 'ALUMNO', 4, 5, 'ACTIVO')
        ])

        cur.executemany("INSERT INTO Libros (libro_id, titulo, autor, editorial, anio_publicacion, tipo_recurso, archivo_pdf_url, carrera_id, descripcion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, 'Redes y Conectividad de Datos', 'Andrew S. Tanenbaum', 'Pearson', 2021, 'HIBRIDO', 'redes_datos.pdf', 1, 'Topologías, protocolos TCP/IP y diseño de redes corporativas.'),
            (2, 'Desarrollo Web con Python y Flask', 'Miguel Grinberg', 'O Reilly', 2023, 'HIBRIDO', 'python_flask.pdf', 1, 'Arquitectura MVC, APIs REST y plantillas Jinja2.'),
            (3, 'Manual de Primeros Auxilios y Soporte Básico', 'Cruz Roja Internacional', 'Médica Panamericana', 2022, 'HIBRIDO', 'primeros_auxilios.pdf', 2, 'Protocolos de atención inicial y evaluación de signos vitales.'),
            (4, 'Farmacología Básica y Clínica', 'Bertram G. Katzung', 'McGraw-Hill', 2021, 'FISICO', None, 2, 'Clasificación de fármacos, dosis terapéuticas y farmacovigilancia.'),
            (5, 'Manejo Agroecológico de Suelos y Cultivos', 'Miguel A. Altieri', 'Mundiprensa', 2022, 'HIBRIDO', 'manejo_suelos.pdf', 3, 'Fertilidad del suelo, rotación de cultivos y control biológico.'),
            (6, 'Contabilidad Financiera y Tributaria', 'Erick Valdivia', 'Instituto Pacífico', 2023, 'HIBRIDO', 'contabilidad_tributaria.pdf', 4, 'Normas NIIF, asientos contables y obligaciones fiscales Sunat.')
        ])

        cur.executemany("INSERT INTO Ejemplares (libro_id, codigo_patrimonio, estado_fisico, ubicacion_estante) VALUES (?, ?, ?, ?)", [
            (1, 'APSTI-001-A', 'DISPONIBLE', 'Estante 1-A'),
            (1, 'APSTI-001-B', 'DISPONIBLE', 'Estante 1-A'),
            (2, 'APSTI-002-A', 'DISPONIBLE', 'Estante 1-B'),
            (3, 'ENF-001-A', 'DISPONIBLE', 'Estante 2-A'),
            (4, 'ENF-002-A', 'DISPONIBLE', 'Estante 2-B'),
            (5, 'AGRO-001-A', 'DISPONIBLE', 'Estante 3-A'),
            (6, 'CONT-001-A', 'DISPONIBLE', 'Estante 4-A')
        ])

        cur.execute("""
            INSERT INTO Prestamos (usuario_id, ejemplar_id, fecha_prestamo, fecha_devolucion_prevista, estado, carnet_custodia, observaciones)
            VALUES (2, 2, '2026-10-25 09:30:00', '2026-11-01 18:00:00', 'ACTIVO', 1, 'Carnet físico en custodia.')
        """)
        conn.commit()

# ==========================================
# CONEXIÓN PRINCIPAL
# ==========================================
def get_db_connection():
    # 1. Si está en Windows, intenta conectar al SQL Server local
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

    # 2. En Render (Linux) o respaldo, usa SQLite integrado
    conn = sqlite3.connect(DB_SQLITE_PATH, check_same_thread=False)
    conn.row_factory = UniversalRow
    conn.create_function("GETDATE", 0, lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    conn.create_function("DATEDIFF", 3, sqlite_datediff)
    seed_cloud_database(conn)
    return CompatConnection(conn)

def get_connection():
    return get_db_connection()

def get_db():
    return get_db_connection()
