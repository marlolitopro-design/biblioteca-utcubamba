import pyodbc

def get_connection():
    # Detecta el controlador de SQL Server disponible en tu sistema
    disponibles = [d for d in pyodbc.drivers() if 'SQL Server' in d]
    driver = disponibles[0] if disponibles else 'SQL Server'
    
    # Cadena de conexión con Autenticación de Windows en tu servidor EQUIPO
    cadena = (
        f"DRIVER={{{driver}}};"
        f"SERVER=EQUIPO;"
        f"DATABASE=BibliotecaUtcubamba;"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cadena)

if __name__ == '__main__':
    try:
        conn = get_connection()
        cursor = conn.cursor()
        print(" Conexión exitosa a SQL Server (BibliotecaUtcubamba)!")
        
        # Probar lectura de las 4 carreras
        cursor.execute("SELECT carrera_id, nombre, codigo FROM Carreras")
        print("\n--- Carreras Registradas en el IESTP Utcubamba ---")
        for fila in cursor.fetchall():
            print(f"[{fila.codigo}] {fila.nombre}")
            
        # Probar lectura de libros
        cursor.execute("SELECT COUNT(*) FROM Libros")
        total_libros = cursor.fetchone()[0]
        print(f"\nTotal de libros cargados en el catálogo: {total_libros}")
        
        conn.close()
    except Exception as e:
        print(" Error al conectar con SQL Server:")
        print(e)