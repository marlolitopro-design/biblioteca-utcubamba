import os
import sys
import re
import subprocess
from datetime import datetime

# ==========================================
# AUTO-INSTALACIÓN AUTOMÁTICA DE PSYCOPG2
# ==========================================
try:
    import psycopg2
except ImportError:
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=False)
        import psycopg2
    except Exception:
        pass

# ==========================================
# TRADUCTOR SQL SERVER -> POSTGRESQL / SQLITE
# ==========================================
def clean_sql(sql, is_postgres=True):
    if not isinstance(sql, str):
        return sql
    
    sql = re.sub(r'VARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'NVARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bDATEDIFF\s*\(\s*([a-zA-Z]+)\s*,', r"DATEDIFF('\1',", sql, flags=re.IGNORECASE)

    sql = re.sub(
        r'\(\s*SELECT\s+TOP\s+(\d+)\s+([^)]+)\)',
        lambda m: f"(SELECT {m.group(2)} LIMIT {m.group(1)})",
        sql,
        flags=re.IGNORECASE
    )

    match = re.search(r'^\s*SELECT\s+TOP\s+(\d+)\s+(.+)', sql, flags=re.IGNORECASE | re.DOTALL)
    if match and not re.search(r'\bLIMIT\b', match.group(2), flags=re.IGNORECASE):
        sql = f"SELECT {match.group(2)} LIMIT {match.group(1)}"

    if is_postgres:
        m_out = re.search(r'OUTPUT\s+INSERTED\.(\w+)', sql, flags=re.IGNORECASE)
        if m_out:
            col = m_out.group(1)
            sql = re.sub(r'OUTPUT\s+INSERTED\.\w+', '', sql, flags=re.IGNORECASE)
            sql = sql.rstrip().rstrip(';') + f" RETURNING {col}"
        sql = re.sub(r'\?', '%s', sql)

    return sql

# ==========================================
# GESTOR DE FILAS Y ADAPTADOR UNIVERSAL
# ==========================================
def normalize_key(k):
    return k.lower().replace('_', '') if isinstance(k, str) else k

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

class UniversalRow(dict):
    def __init__(self, cursor, row):
        super().__init__()
        self._keys = [col.name if hasattr(col, 'name') else col[0] for col in cursor.description]
        self._row = [parse_date_if_str(v) for v in row]
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
    def __init__(self, cur, is_postgres=True):
        self._cur = cur
        self._is_postgres = is_postgres
        self._inserted_id = None

    def execute(self, sql, params=None):
        self._inserted_id = None
        sql_clean = clean_sql(sql, self._is_postgres)
        if self._is_postgres:
            if params is None or len(params) == 0:
                return self._cur.execute(sql_clean)
            return self._cur.execute(sql_clean, tuple(params))
        
        m_out = re.search(r'OUTPUT\s+INSERTED\.(\w+)', sql, flags=re.IGNORECASE)
        if m_out:
            sql_clean = re.sub(r'OUTPUT\s+INSERTED\.\w+', '', sql_clean, flags=re.IGNORECASE)
            res = self._cur.execute(sql_clean, params or ())
            self._inserted_id = (self._cur.lastrowid,)
            return res
        return self._cur.execute(sql_clean, params or ())

    def executemany(self, sql, seq):
        sql_clean = clean_sql(sql, self._is_postgres)
        if self._is_postgres:
            if not seq:
                return
            return self._cur.executemany(sql_clean, [tuple(x) for x in seq])
        return self._cur.executemany(sql_clean, seq)

    def fetchone(self):
        if self._inserted_id is not None:
            val = self._inserted_id
            self._inserted_id = None
            return val
        row = self._cur.fetchone()
        return UniversalRow(self._cur, row) if row else None

    def fetchall(self):
        rows = self._cur.fetchall()
        return [UniversalRow(self._cur, r) for r in rows] if rows else []

    def __iter__(self):
        while True:
            r = self.fetchone()
            if r is None:
                break
            yield r

    def __getattr__(self, name):
        return getattr(self._cur, name)

class CompatConnection:
    def __init__(self, conn, is_postgres=True):
        self._conn = conn
        self._is_postgres = is_postgres

    def cursor(self):
        return CompatCursor(self._conn.cursor(), self._is_postgres)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

# ==========================================
# AUTO-CREACIÓN DE TABLAS Y DATOS
# ==========================================
def seed_database(conn, is_postgres=True):
    cur = conn.cursor()
    if is_postgres:
        cur.execute("""
            CREATE OR REPLACE FUNCTION GETDATE() RETURNS TIMESTAMP AS $$ BEGIN RETURN CURRENT_TIMESTAMP; END; $$ LANGUAGE plpgsql;
            CREATE OR REPLACE FUNCTION DATEDIFF(unit TEXT, d1 TIMESTAMP, d2 TIMESTAMP) RETURNS INTEGER AS $$ BEGIN RETURN (d2::date - d1::date); END; $$ LANGUAGE plpgsql;
        """)

    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_now = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" if is_postgres else "TEXT"

    schema_sql = f"""
        CREATE TABLE IF NOT EXISTS Carreras (
            carrera_id {pk_type},
            nombre VARCHAR(120) NOT NULL,
            codigo VARCHAR(20) UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS Usuarios (
            usuario_id {pk_type},
            dni VARCHAR(15) UNIQUE NOT NULL,
            nombres VARCHAR(100) NOT NULL,
            apellidos VARCHAR(100) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            rol VARCHAR(20) NOT NULL DEFAULT 'ALUMNO',
            carrera_id INTEGER,
            ciclo INTEGER DEFAULT 1,
            estado VARCHAR(20) DEFAULT 'ACTIVO'
        );
        CREATE TABLE IF NOT EXISTS Libros (
            libro_id {pk_type},
            titulo VARCHAR(255) NOT NULL,
            autor VARCHAR(200) NOT NULL,
            editorial VARCHAR(150),
            anio_publicacion INTEGER,
            isbn VARCHAR(50),
            tipo_recurso VARCHAR(20) DEFAULT 'HIBRIDO',
            archivo_pdf_url VARCHAR(255),
            descripcion TEXT
        );
        CREATE TABLE IF NOT EXISTS LibroCarrera (
            libro_id INTEGER NOT NULL,
            carrera_id INTEGER NOT NULL,
            PRIMARY KEY (libro_id, carrera_id)
        );
        CREATE TABLE IF NOT EXISTS Ejemplares (
            ejemplar_id {pk_type},
            libro_id INTEGER NOT NULL,
            codigo_patrimonio VARCHAR(50) UNIQUE NOT NULL,
            estado_fisico VARCHAR(30) DEFAULT 'DISPONIBLE',
            ubicacion_estante VARCHAR(100) DEFAULT 'Estante 1-A'
        );
        CREATE TABLE IF NOT EXISTS Prestamos (
            prestamo_id {pk_type},
            usuario_id INTEGER NOT NULL,
            ejemplar_id INTEGER NOT NULL,
            fecha_prestamo {ts_now},
            fecha_devolucion_prevista {ts_now},
            fecha_devolucion_real {ts_now},
            estado VARCHAR(20) DEFAULT 'ACTIVO',
            carnet_custodia INTEGER DEFAULT 1,
            observaciones VARCHAR(255)
        );
        CREATE TABLE IF NOT EXISTS AccesosDigitales (
            acceso_id {pk_type},
            usuario_id INTEGER NOT NULL,
            libro_id INTEGER NOT NULL,
            fecha_acceso {ts_now},
            direccion_ip VARCHAR(50) DEFAULT '127.0.0.1'
        );
    """

    if is_postgres:
        cur.execute(schema_sql)
    else:
        conn.executescript(schema_sql)

    cur.execute("SELECT COUNT(*) FROM Carreras")
    if cur.fetchone()[0] == 0:
        ph = "%s" if is_postgres else "?"
        cur.executemany(f"INSERT INTO Carreras (nombre, codigo) VALUES ({ph}, {ph})", [
            ('Arquitectura de Plataformas y TI (APSTI)', 'APSTI'),
            ('Enfermería Técnica', 'ENF'),
            ('Producción Agropecuaria', 'AGRO'),
            ('Contabilidad', 'CONT')
        ])

        ph8 = ", ".join([ph]*8)
        cur.executemany(f"INSERT INTO Usuarios (dni, nombres, apellidos, password_hash, rol, carrera_id, ciclo, estado) VALUES ({ph8})", [
            ('admin', 'Administrador', 'Biblioteca Central', 'admin123', 'ADMIN', 1, 6, 'ACTIVO'),
            ('74859612', 'Marlo', 'Vilchez Cuzque', '74859612', 'ALUMNO', 1, 6, 'ACTIVO'),
            ('71234567', 'Rosa María', 'Díaz López', '71234567', 'ALUMNO', 2, 4, 'ACTIVO'),
            ('72345678', 'Juan Carlos', 'Huamán Quispe', '72345678', 'ALUMNO', 3, 2, 'ACTIVO'),
            ('73456789', 'Ana Lucía', 'Pérez Torres', '73456789', 'ALUMNO', 4, 5, 'ACTIVO')
        ])

        ph7 = ", ".join([ph]*7)
        cur.executemany(f"INSERT INTO Libros (titulo, autor, editorial, anio_publicacion, tipo_recurso, archivo_pdf_url, descripcion) VALUES ({ph7})", [
            ('Redes y Conectividad de Datos', 'Andrew S. Tanenbaum', 'Pearson', 2021, 'HIBRIDO', 'redes_datos.pdf', 'Topologías, protocolos TCP/IP y diseño de redes corporativas.'),
            ('Desarrollo Web con Python y Flask', 'Miguel Grinberg', 'O Reilly', 2023, 'HIBRIDO', 'python_flask.pdf', 'Arquitectura MVC, APIs REST y plantillas Jinja2.'),
            ('Manual de Primeros Auxilios y Soporte Básico', 'Cruz Roja Internacional', 'Médica Panamericana', 2022, 'HIBRIDO', 'primeros_auxilios.pdf', 'Protocolos de atención inicial y evaluación de signos vitales.'),
            ('Farmacología Básica y Clínica', 'Bertram G. Katzung', 'McGraw-Hill', 2021, 'FISICO', None, 'Clasificación de fármacos, dosis terapéuticas y farmacovigilancia.'),
            ('Manejo Agroecológico de Suelos y Cultivos', 'Miguel A. Altieri', 'Mundiprensa', 2022, 'HIBRIDO', 'manejo_suelos.pdf', 'Fertilidad del suelo, rotación de cultivos y control biológico.'),
            ('Contabilidad Financiera y Tributaria', 'Erick Valdivia', 'Instituto Pacífico', 2023, 'HIBRIDO', 'contabilidad_tributaria.pdf', 'Normas NIIF, asientos contables y obligaciones fiscales Sunat.')
        ])

        cur.executemany(f"INSERT INTO LibroCarrera (libro_id, carrera_id) VALUES ({ph}, {ph})", [
            (1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 4)
        ])

        ph4 = ", ".join([ph]*4)
        cur.executemany(f"INSERT INTO Ejemplares (libro_id, codigo_patrimonio, estado_fisico, ubicacion_estante) VALUES ({ph4})", [
            (1, 'APSTI-001-A', 'DISPONIBLE', 'Estante 1-A'),
            (1, 'APSTI-001-B', 'DISPONIBLE', 'Estante 1-A'),
            (2, 'APSTI-002-A', 'DISPONIBLE', 'Estante 1-B'),
            (3, 'ENF-001-A', 'DISPONIBLE', 'Estante 2-A'),
            (4, 'ENF-002-A', 'DISPONIBLE', 'Estante 2-B'),
            (5, 'AGRO-001-A', 'DISPONIBLE', 'Estante 3-A'),
            (6, 'CONT-001-A', 'DISPONIBLE', 'Estante 4-A')
        ])

    conn.commit()

# ==========================================
# CONEXIÓN PRINCIPAL
# ==========================================
def get_db_connection():
    # 1. En Windows local: SQL Server EQUIPO
    if sys.platform.startswith('win'):
        try:
            import pyodbc
            conn_str = "DRIVER={ODBC Driver 17 for SQL Server};SERVER=EQUIPO;DATABASE=BibliotecaUtcubamba;Trusted_Connection=yes;"
            return pyodbc.connect(conn_str)
        except Exception:
            pass

    # 2. Conexión oficial a Supabase PostgreSQL (IPv4 Session Pooler)
    try:
        global psycopg2
        if 'psycopg2' not in sys.modules:
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=False)
                import psycopg2
            except Exception:
                pass
        import psycopg2
        conn = psycopg2.connect(
            host="aws-0-us-east-2.pooler.supabase.com",
            port=5432,
            user="postgres.eolwyomlogeobdvkrgmw",
            password="Utcubamba2026*",
            dbname="postgres",
            sslmode="require",
            connect_timeout=10
        )
        conn.autocommit = True
        seed_database(conn, True)
        return CompatConnection(conn, True)
    except Exception as e:
        print(f"Aviso Supabase: {e}")

    # 3. Respaldo local SQLite auto-inicializado
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'biblioteca_cloud.db')
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.create_function("GETDATE", 0, lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    conn.create_function("DATEDIFF", 3, lambda u, d1, d2: 0)
    seed_database(conn, False)
    return CompatConnection(conn, False)

def get_connection():
    return get_db_connection()

def get_db():
    return get_db_connection()
