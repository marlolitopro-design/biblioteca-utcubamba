from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta
from db import get_connection

app = Flask(__name__)
app.secret_key = 'clave_secreta_institucional_utcubamba_2026'

@app.route('/')
def index():
    if session.get('usuario'):
        if session['usuario']['rol'] == 'ADMIN':
            return redirect(url_for('dashboard'))
        return redirect(url_for('alumno_inicio'))
    return redirect(url_for('catalogo'))

# -------------------------------------------------------------
# CATÁLOGO DE RECURSOS
# -------------------------------------------------------------
@app.route('/catalogo')
def catalogo():
    carrera_filtro = request.args.get('carrera', '').strip()
    busqueda = request.args.get('q', '').strip()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT carrera_id, nombre, codigo FROM Carreras ORDER BY carrera_id")
    carreras = [dict(carrera_id=r[0], nombre=r[1], codigo=r[2]) for r in cursor.fetchall()]

    query = """
    SELECT 
        l.libro_id, 
        l.titulo, 
        l.autor, 
        l.editorial, 
        l.anio_publicacion, 
        l.tipo_recurso, 
        l.archivo_pdf_url, 
        CAST(l.descripcion AS VARCHAR(MAX)) as descripcion,
        (SELECT COUNT(*) FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico != 'BAJA') as total_copias,
        (SELECT COUNT(*) FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico = 'DISPONIBLE') as disponibles,
        (SELECT TOP 1 e.ubicacion_estante FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico != 'BAJA') as estante,
        l.portada_url
    FROM Libros l
    WHERE 1=1
    """
    params = []

    if busqueda:
        query += " AND (l.titulo LIKE ? OR l.autor LIKE ?)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%"])

    if carrera_filtro:
        query += """
        AND l.libro_id IN (
            SELECT lc.libro_id 
            FROM LibroCarrera lc 
            JOIN Carreras c ON lc.carrera_id = c.carrera_id 
            WHERE c.codigo = ?
        )
        """
        params.append(carrera_filtro)

    query += " ORDER BY l.titulo ASC"
    cursor.execute(query, params)
    filas = cursor.fetchall()

    libros = []
    for fila in filas:
        lid = fila[0]
        cursor.execute("""
            SELECT c.codigo 
            FROM LibroCarrera lc 
            JOIN Carreras c ON lc.carrera_id = c.carrera_id 
            WHERE lc.libro_id = ?
        """, (lid,))
        carreras_codigos = [c[0] for c in cursor.fetchall()]

        libros.append({
            'libro_id': fila[0],
            'titulo': fila[1],
            'autor': fila[2],
            'editorial': fila[3],
            'anio_publicacion': fila[4],
            'tipo_recurso': fila[5],
            'archivo_pdf_url': fila[6],
            'descripcion': fila[7],
            'total_copias': fila[8],
            'disponibles': fila[9],
            'estante': fila[10],
            'portada_url': fila[11] if len(fila) > 11 and fila[11] else None,
            'carreras_codigos': carreras_codigos
        })

    cursor.execute("SELECT COUNT(*) FROM Libros")
    total_libros = cursor.fetchone()[0]
    conn.close()

    return render_template(
        'catalogo.html',
        libros=libros,
        carreras=carreras,
        carrera_sel=carrera_filtro,
        busqueda=busqueda,
        total_libros=total_libros
    )

# -------------------------------------------------------------
# LOGIN Y LOGOUT
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        dni = request.form.get('dni', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT usuario_id, dni, nombres, apellidos, password_hash, rol, estado 
            FROM Usuarios 
            WHERE dni = ?
        """, (dni,))
        user = cursor.fetchone()
        conn.close()

        if user and (user.password_hash == password):
            if user.estado != 'ACTIVO':
                flash('Su cuenta se encuentra inhabilitada. Contacte a biblioteca.', 'danger')
                return render_template('login.html')

            session['usuario'] = {
                'id': user.usuario_id,
                'dni': user.dni,
                'nombres': f"{user.nombres} {user.apellidos}",
                'rol': user.rol
            }
            flash(f'¡Bienvenido(a) {user.nombres}!', 'success')
            
            if user.rol == 'ADMIN':
                return redirect(url_for('dashboard'))
            return redirect(url_for('alumno_inicio'))
        else:
            flash('DNI o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('catalogo'))

# -------------------------------------------------------------
# ENTORNO DEL ALUMNO (Inicio, Mis Préstamos, Perfil y Lector)
# -------------------------------------------------------------
@app.route('/alumno/inicio')
def alumno_inicio():
    if not session.get('usuario') or session['usuario']['rol'] != 'ALUMNO':
        flash('Debe iniciar sesión como estudiante.', 'warning')
        return redirect(url_for('login'))

    usuario_id = session['usuario']['id']
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT u.usuario_id, u.dni, u.nombres, u.apellidos, c.carrera_id, c.nombre as carrera_nombre, c.codigo as carrera_codigo, u.ciclo, u.estado
        FROM Usuarios u
        LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
        WHERE u.usuario_id = ?
    """, (usuario_id,))
    row = cursor.fetchone()
    alumno = {
        'usuario_id': row[0], 'dni': row[1], 'nombres': row[2], 'apellidos': row[3],
        'carrera_id': row[4], 'carrera_nombre': row[5], 'carrera_codigo': row[6],
        'ciclo': row[7], 'estado': row[8]
    }

    cursor.execute("SELECT COUNT(*) FROM Prestamos WHERE usuario_id = ? AND estado = 'ACTIVO'", (usuario_id,))
    prestamos_activos_conteo = cursor.fetchone()[0]

    cursor.execute("""
        SELECT l.libro_id, l.titulo, l.autor, l.anio_publicacion, l.tipo_recurso, l.archivo_pdf_url,
               CAST(l.descripcion AS VARCHAR(MAX)) as descripcion,
               (SELECT COUNT(*) FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico = 'DISPONIBLE') as disponibles
        FROM Libros l
        JOIN LibroCarrera lc ON l.libro_id = lc.libro_id
        WHERE lc.carrera_id = ?
        ORDER BY l.titulo ASC
    """, (alumno['carrera_id'],))
    recomendados = [
        dict(
            libro_id=r[0], titulo=r[1], autor=r[2], anio_publicacion=r[3],
            tipo_recurso=r[4], archivo_pdf_url=r[5], descripcion=r[6], disponibles=r[7]
        )
        for r in cursor.fetchall()
    ]

    conn.close()

    return render_template(
        'alumno_inicio.html',
        alumno=alumno,
        prestamos_activos_conteo=prestamos_activos_conteo,
        recomendados=recomendados
    )

@app.route('/alumno/mis-prestamos')
def alumno_prestamos():
    if not session.get('usuario') or session['usuario']['rol'] != 'ALUMNO':
        return redirect(url_for('login'))

    usuario_id = session['usuario']['id']
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT u.usuario_id, u.dni, u.nombres, u.apellidos, c.nombre as carrera_nombre, u.ciclo, u.estado
        FROM Usuarios u
        LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
        WHERE u.usuario_id = ?
    """, (usuario_id,))
    row = cursor.fetchone()
    alumno = {
        'usuario_id': row[0], 'dni': row[1], 'nombres': row[2], 'apellidos': row[3],
        'carrera_nombre': row[4], 'ciclo': row[5], 'estado': row[6]
    }

    cursor.execute("""
        SELECT p.prestamo_id, l.titulo, l.autor, e.codigo_patrimonio, p.fecha_prestamo, p.fecha_devolucion_prevista,
               DATEDIFF(day, p.fecha_devolucion_prevista, GETDATE()) as dias_retraso
        FROM Prestamos p
        JOIN Ejemplares e ON p.ejemplar_id = e.ejemplar_id
        JOIN Libros l ON e.libro_id = l.libro_id
        WHERE p.usuario_id = ? AND p.estado = 'ACTIVO'
        ORDER BY p.fecha_devolucion_prevista ASC
    """, (usuario_id,))
    prestamos_activos = [
        dict(
            prestamo_id=r[0], titulo=r[1], autor=r[2], codigo_patrimonio=r[3],
            fecha_prestamo=r[4], fecha_devolucion_prevista=r[5], dias_retraso=r[6]
        )
        for r in cursor.fetchall()
    ]

    # Últimas lecturas digitales del estudiante
    cursor.execute("""
        SELECT TOP 5 l.libro_id, l.titulo, l.autor, MAX(ad.fecha_acceso) as ultima_lectura
        FROM AccesosDigitales ad
        JOIN Libros l ON ad.libro_id = l.libro_id
        WHERE ad.usuario_id = ?
        GROUP BY l.libro_id, l.titulo, l.autor
        ORDER BY ultima_lectura DESC
    """, (usuario_id,))
    lecturas_digitales = [
        dict(libro_id=r[0], titulo=r[1], autor=r[2], fecha_acceso=r[3])
        for r in cursor.fetchall()
    ]

    cursor.execute("""
        SELECT l.titulo, e.codigo_patrimonio, p.fecha_devolucion_real
        FROM Prestamos p
        JOIN Ejemplares e ON p.ejemplar_id = e.ejemplar_id
        JOIN Libros l ON e.libro_id = l.libro_id
        WHERE p.usuario_id = ? AND p.estado = 'DEVUELTO'
        ORDER BY p.fecha_devolucion_real DESC
    """, (usuario_id,))
    historial_devueltos = [
        dict(titulo=r[0], codigo_patrimonio=r[1], fecha_devolucion_real=r[2])
        for r in cursor.fetchall()
    ]

    conn.close()

    return render_template(
        'alumno_prestamos.html',
        alumno=alumno,
        prestamos_activos=prestamos_activos,
        lecturas_digitales=lecturas_digitales,
        historial_devueltos=historial_devueltos
    )

@app.route('/alumno/perfil', methods=['GET', 'POST'])
def alumno_perfil():
    if not session.get('usuario') or session['usuario']['rol'] != 'ALUMNO':
        return redirect(url_for('login'))

    usuario_id = session['usuario']['id']
    conn = get_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        actual = request.form.get('password_actual', '').strip()
        nueva = request.form.get('password_nueva', '').strip()
        confirmar = request.form.get('password_confirmar', '').strip()

        cursor.execute("SELECT password_hash FROM Usuarios WHERE usuario_id = ?", (usuario_id,))
        clave_bd = cursor.fetchone()[0]

        if clave_bd != actual:
            flash('La contraseña actual ingresada es incorrecta.', 'danger')
        elif nueva != confirmar:
            flash('La nueva contraseña y la confirmación no coinciden.', 'warning')
        else:
            cursor.execute("UPDATE Usuarios SET password_hash = ? WHERE usuario_id = ?", (nueva, usuario_id))
            conn.commit()
            flash('¡Tu contraseña ha sido actualizada con éxito!', 'success')

    cursor.execute("""
        SELECT u.dni, u.nombres, u.apellidos, c.nombre as carrera_nombre, u.ciclo, u.rol
        FROM Usuarios u
        LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
        WHERE u.usuario_id = ?
    """, (usuario_id,))
    r = cursor.fetchone()
    alumno = {
        'dni': r[0], 'nombres': r[1], 'apellidos': r[2], 'carrera_nombre': r[3],
        'ciclo': r[4], 'rol': r[5]
    }
    conn.close()

    return render_template('alumno_perfil.html', alumno=alumno)

@app.route('/leer/<int:libro_id>')
def leer_libro(libro_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT libro_id, titulo, autor, archivo_pdf_url FROM Libros WHERE libro_id = ?", (libro_id,))
    r = cursor.fetchone()
    if not r:
        conn.close()
        flash('El recurso bibliográfico no existe.', 'warning')
        return redirect(url_for('catalogo'))

    libro = {'libro_id': r[0], 'titulo': r[1], 'autor': r[2], 'archivo_pdf_url': r[3]}

    if session.get('usuario'):
        uid = session['usuario']['id']
        ip = request.remote_addr
        cursor.execute("""
            INSERT INTO AccesosDigitales (usuario_id, libro_id, fecha_acceso, direccion_ip)
            VALUES (?, ?, GETDATE(), ?)
        """, (uid, libro_id, ip))
        conn.commit()

    conn.close()
    return render_template('visor.html', libro=libro)

# -------------------------------------------------------------
# DASHBOARD DE CONTROL (Admin)
# -------------------------------------------------------------
@app.route('/admin/dashboard')
def dashboard():
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        flash('Acceso restringido para el administrador.', 'warning')
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM Libros")
    total_titulos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Ejemplares WHERE estado_fisico != 'BAJA'")
    total_copias = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Ejemplares WHERE estado_fisico = 'DISPONIBLE'")
    copias_disponibles = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Prestamos WHERE estado = 'ACTIVO'")
    prestamos_activos_total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Prestamos WHERE estado = 'ACTIVO' AND fecha_devolucion_prevista < GETDATE()")
    prestamos_vencidos_total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Usuarios WHERE rol = 'ALUMNO'")
    total_alumnos = cursor.fetchone()[0]

    cursor.execute("""
        SELECT c.codigo, c.nombre, COUNT(u.usuario_id) as total
        FROM Carreras c
        LEFT JOIN Usuarios u ON c.carrera_id = u.carrera_id AND u.rol = 'ALUMNO'
        GROUP BY c.codigo, c.nombre, c.carrera_id
        ORDER BY c.carrera_id
    """)
    resumen_carreras = [dict(codigo=r[0], nombre=r[1], total_alumnos=r[2]) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT p.prestamo_id, u.dni, u.nombres, u.apellidos, c.codigo as carrera_codigo, u.ciclo,
               l.titulo, e.codigo_patrimonio, p.fecha_prestamo, p.fecha_devolucion_prevista,
               DATEDIFF(day, p.fecha_devolucion_prevista, GETDATE()) as dias_retraso
        FROM Prestamos p
        JOIN Usuarios u ON p.usuario_id = u.usuario_id
        JOIN Ejemplares e ON p.ejemplar_id = e.ejemplar_id
        JOIN Libros l ON e.libro_id = l.libro_id
        LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
        WHERE p.estado = 'ACTIVO'
        ORDER BY p.fecha_devolucion_prevista ASC
    """)
    reporte_prestamos = [
        dict(
            prestamo_id=r[0], dni=r[1], nombres=r[2], apellidos=r[3], carrera_codigo=r[4], ciclo=r[5],
            titulo=r[6], codigo_patrimonio=r[7], fecha_prestamo=r[8], fecha_devolucion_prevista=r[9],
            dias_retraso=r[10]
        )
        for r in cursor.fetchall()
    ]
    conn.close()

    return render_template(
        'dashboard.html',
        total_titulos=total_titulos,
        total_copias=total_copias,
        copias_disponibles=copias_disponibles,
        prestamos_activos_total=prestamos_activos_total,
        prestamos_vencidos_total=prestamos_vencidos_total,
        total_alumnos=total_alumnos,
        resumen_carreras=resumen_carreras,
        reporte_prestamos=reporte_prestamos
    )

# -------------------------------------------------------------
# MOSTRADOR DEL ADMINISTRADOR
# -------------------------------------------------------------
@app.route('/admin/mostrador')
def mostrador():
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        flash('Acceso restringido para el administrador.', 'warning')
        return redirect(url_for('login'))

    dni_buscado = request.args.get('dni', '').strip()
    alumno = None

    conn = get_connection()
    cursor = conn.cursor()

    if dni_buscado:
        cursor.execute("""
            SELECT u.usuario_id, u.dni, u.nombres, u.apellidos, c.nombre as carrera_nombre, u.ciclo,
                   (SELECT COUNT(*) FROM Prestamos p WHERE p.usuario_id = u.usuario_id AND p.estado = 'ACTIVO') as prestamos_activos
            FROM Usuarios u
            LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
            WHERE u.dni = ? AND u.rol = 'ALUMNO' AND u.estado = 'ACTIVO'
        """, (dni_buscado,))
        row = cursor.fetchone()
        if row:
            alumno = {
                'usuario_id': row[0],
                'dni': row[1],
                'nombres': row[2],
                'apellidos': row[3],
                'carrera_nombre': row[4],
                'ciclo': row[5],
                'prestamos_activos': row[6]
            }

    cursor.execute("""
        SELECT e.ejemplar_id, l.titulo, e.codigo_patrimonio, e.ubicacion_estante
        FROM Ejemplares e
        JOIN Libros l ON e.libro_id = l.libro_id
        WHERE e.estado_fisico = 'DISPONIBLE'
        ORDER BY l.titulo ASC
    """)
    ejemplares_libres = [
        dict(ejemplar_id=r[0], titulo=r[1], codigo_patrimonio=r[2], ubicacion_estante=r[3])
        for r in cursor.fetchall()
    ]

    cursor.execute("""
        SELECT p.prestamo_id, u.nombres, u.apellidos, u.dni, l.titulo, e.codigo_patrimonio, p.fecha_devolucion_prevista
        FROM Prestamos p
        JOIN Usuarios u ON p.usuario_id = u.usuario_id
        JOIN Ejemplares e ON p.ejemplar_id = e.ejemplar_id
        JOIN Libros l ON e.libro_id = l.libro_id
        WHERE p.estado = 'ACTIVO'
        ORDER BY p.fecha_prestamo DESC
    """)
    prestamos_activos = [
        dict(
            prestamo_id=r[0],
            nombres=r[1],
            apellidos=r[2],
            dni=r[3],
            titulo=r[4],
            codigo_patrimonio=r[5],
            fecha_devolucion_prevista=r[6]
        )
        for r in cursor.fetchall()
    ]
    conn.close()

    return render_template(
        'mostrador.html',
        alumno=alumno,
        dni_buscado=dni_buscado,
        ejemplares_libres=ejemplares_libres,
        prestamos_activos=prestamos_activos
    )

@app.route('/admin/prestar', methods=['POST'])
def registrar_prestamo():
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    usuario_id = request.form.get('usuario_id')
    ejemplar_id = request.form.get('ejemplar_id')
    dni = request.form.get('dni')

    if not usuario_id or not ejemplar_id:
        flash('Debe seleccionar un ejemplar válido.', 'warning')
        return redirect(url_for('mostrador', dni=dni))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM Prestamos WHERE usuario_id = ? AND estado = 'ACTIVO'", (usuario_id,))
    activos = cursor.fetchone()[0]
    if activos >= 2:
        flash('Operación denegada: El alumno ya tiene 2 libros en préstamo.', 'danger')
        conn.close()
        return redirect(url_for('mostrador', dni=dni))

    fecha_limite = datetime.now() + timedelta(days=7)

    cursor.execute("""
        INSERT INTO Prestamos (usuario_id, ejemplar_id, fecha_prestamo, fecha_devolucion_prevista, estado)
        VALUES (?, ?, GETDATE(), ?, 'ACTIVO')
    """, (usuario_id, ejemplar_id, fecha_limite))

    cursor.execute("UPDATE Ejemplares SET estado_fisico = 'PRESTADO' WHERE ejemplar_id = ?", (ejemplar_id,))
    conn.commit()
    conn.close()

    flash('¡Préstamo registrado exitosamente y carnet retenido en mostrador!', 'success')
    return redirect(url_for('mostrador', dni=dni))

@app.route('/admin/devolver/<int:prestamo_id>', methods=['POST'])
def registrar_devolucion(prestamo_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    estado_retorno = request.form.get('estado_retorno', 'DISPONIBLE')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ejemplar_id FROM Prestamos WHERE prestamo_id = ?", (prestamo_id,))
    fila = cursor.fetchone()
    if fila:
        ejemplar_id = fila[0]
        cursor.execute("""
            UPDATE Prestamos 
            SET estado = 'DEVUELTO', fecha_devolucion_real = GETDATE(), observaciones = ?
            WHERE prestamo_id = ?
        """, (f"Retornado en condición: {estado_retorno}", prestamo_id))

        cursor.execute("UPDATE Ejemplares SET estado_fisico = ? WHERE ejemplar_id = ?", (estado_retorno, ejemplar_id))
        conn.commit()
        
        if estado_retorno == 'DISPONIBLE':
            flash('¡Libro recibido en buen estado! Ejemplar disponible en sala. Entregue su carnet físico al alumno.', 'success')
        else:
            flash('Libro registrado como DAÑADO y enviado a MANTENIMIENTO. Entregue o retenga el carnet según evaluación.', 'warning')

    conn.close()
    return redirect(url_for('mostrador'))

# -------------------------------------------------------------
# GESTIÓN DE ESTUDIANTES
# -------------------------------------------------------------
@app.route('/admin/alumnos')
def listar_alumnos():
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        flash('Acceso restringido para el administrador.', 'warning')
        return redirect(url_for('login'))

    busqueda = request.args.get('q', '').strip()
    carrera_filtro = request.args.get('carrera', '').strip()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT carrera_id, nombre, codigo FROM Carreras ORDER BY carrera_id")
    carreras = [dict(carrera_id=r[0], nombre=r[1], codigo=r[2]) for r in cursor.fetchall()]

    query = """
    SELECT u.usuario_id, u.dni, u.nombres, u.apellidos, u.ciclo, u.estado, u.carrera_id,
           c.nombre as carrera_nombre, c.codigo as carrera_codigo,
           (SELECT COUNT(*) FROM Prestamos p WHERE p.usuario_id = u.usuario_id AND p.estado = 'ACTIVO') as prestamos_activos
    FROM Usuarios u
    LEFT JOIN Carreras c ON u.carrera_id = c.carrera_id
    WHERE u.rol = 'ALUMNO'
    """
    params = []

    if busqueda:
        query += " AND (u.dni LIKE ? OR u.nombres LIKE ? OR u.apellidos LIKE ?)"
        params.extend([f"%{busqueda}%", f"%{busqueda}%", f"%{busqueda}%"])

    if carrera_filtro:
        query += " AND u.carrera_id = ?"
        params.append(carrera_filtro)

    query += " ORDER BY u.apellidos ASC, u.nombres ASC"
    cursor.execute(query, params)

    alumnos = [
        dict(
            usuario_id=r[0], dni=r[1], nombres=r[2], apellidos=r[3], ciclo=r[4],
            estado=r[5], carrera_id=r[6], carrera_nombre=r[7], carrera_codigo=r[8],
            prestamos_activos=r[9]
        )
        for r in cursor.fetchall()
    ]
    conn.close()

    return render_template('alumnos.html', alumnos=alumnos, carreras=carreras, busqueda=busqueda, carrera_sel=carrera_filtro)

@app.route('/admin/alumnos/crear', methods=['POST'])
def crear_alumno():
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    dni = request.form.get('dni', '').strip()
    nombres = request.form.get('nombres', '').strip()
    apellidos = request.form.get('apellidos', '').strip()
    carrera_id = request.form.get('carrera_id')
    ciclo = request.form.get('ciclo')

    if len(dni) != 8 or not dni.isdigit():
        flash('El DNI debe contener exactamente 8 dígitos numéricos.', 'danger')
        return redirect(url_for('listar_alumnos'))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario_id FROM Usuarios WHERE dni = ?", (dni,))
    if cursor.fetchone():
        flash(f'El DNI {dni} ya se encuentra registrado en el padrón.', 'warning')
        conn.close()
        return redirect(url_for('listar_alumnos'))

    cursor.execute("""
        INSERT INTO Usuarios (dni, nombres, apellidos, password_hash, rol, carrera_id, ciclo, estado)
        VALUES (?, ?, ?, ?, 'ALUMNO', ?, ?, 'ACTIVO')
    """, (dni, nombres, apellidos, dni, carrera_id, ciclo))

    conn.commit()
    conn.close()

    flash(f'¡Estudiante {nombres} {apellidos} registrado exitosamente!', 'success')
    return redirect(url_for('listar_alumnos'))

@app.route('/admin/alumnos/editar/<int:usuario_id>', methods=['POST'])
def editar_alumno(usuario_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    nombres = request.form.get('nombres', '').strip()
    apellidos = request.form.get('apellidos', '').strip()
    carrera_id = request.form.get('carrera_id')
    ciclo = request.form.get('ciclo')
    estado = request.form.get('estado')

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Usuarios 
        SET nombres = ?, apellidos = ?, carrera_id = ?, ciclo = ?, estado = ?
        WHERE usuario_id = ?
    """, (nombres, apellidos, carrera_id, ciclo, estado, usuario_id))

    conn.commit()
    conn.close()
    flash('Datos del estudiante actualizados correctamente.', 'success')
    return redirect(url_for('listar_alumnos'))

@app.route('/admin/alumnos/reset/<int:usuario_id>', methods=['POST'])
def reset_clave_alumno(usuario_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT dni FROM Usuarios WHERE usuario_id = ?", (usuario_id,))
    fila = cursor.fetchone()
    if fila:
        dni = fila[0]
        cursor.execute("UPDATE Usuarios SET password_hash = ? WHERE usuario_id = ?", (dni, usuario_id))
        conn.commit()
        flash(f'Contraseña restablecida con éxito al DNI ({dni}).', 'info')

    conn.close()
    return redirect(url_for('listar_alumnos'))

@app.route('/admin/alumnos/eliminar/<int:usuario_id>', methods=['POST'])
def eliminar_alumno(usuario_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM Prestamos WHERE usuario_id = ?", (usuario_id,))
    tiene_prestamos = cursor.fetchone()[0]

    if tiene_prestamos > 0:
        cursor.execute("UPDATE Usuarios SET estado = 'INACTIVO' WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
        flash('El estudiante registra historial de préstamos; fue desactivado para preservar auditoría.', 'warning')
    else:
        cursor.execute("DELETE FROM AccesosDigitales WHERE usuario_id = ?", (usuario_id,))
        cursor.execute("DELETE FROM Usuarios WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
        flash('Estudiante eliminado definitivamente de la base de datos.', 'success')

    conn.close()
    return redirect(url_for('listar_alumnos'))

# -------------------------------------------------------------
# GESTIÓN DE LIBROS E INVENTARIO (Títulos, Copias, Estantes y Reparación)
# -------------------------------------------------------------
@app.route('/admin/libros', methods=['GET', 'POST'])
def listar_libros():
    if request.method == 'POST':
        return crear_libro()

    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        flash('Acceso restringido para el administrador.', 'warning')
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT carrera_id, nombre, codigo FROM Carreras ORDER BY carrera_id")
    carreras = [dict(carrera_id=r[0], nombre=r[1], codigo=r[2]) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT l.libro_id, l.titulo, l.autor, l.editorial, l.anio_publicacion, l.tipo_recurso, l.archivo_pdf_url,
               CAST(l.descripcion AS VARCHAR(MAX)) as descripcion,
               (SELECT COUNT(*) FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico != 'BAJA') as total_copias,
               (SELECT COUNT(*) FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico = 'DISPONIBLE') as disponibles,
               (SELECT TOP 1 e.ubicacion_estante FROM Ejemplares e WHERE e.libro_id = l.libro_id AND e.estado_fisico != 'BAJA') as estante_principal,
               l.portada_url
        FROM Libros l
        ORDER BY l.titulo ASC
    """)
    filas = cursor.fetchall()

    libros = []
    for f in filas:
        lid = f[0]
        cursor.execute("""
            SELECT c.codigo, c.carrera_id 
            FROM LibroCarrera lc 
            JOIN Carreras c ON lc.carrera_id = c.carrera_id 
            WHERE lc.libro_id = ?
        """, (lid,))
        rel = cursor.fetchall()
        carreras_codigos = [r[0] for r in rel]
        carreras_ids = [str(r[1]) for r in rel]

        # Obtener todas las copias físicas de este libro para poder editar su estante o código
        cursor.execute("""
            SELECT ejemplar_id, codigo_patrimonio, estado_fisico, ubicacion_estante
            FROM Ejemplares
            WHERE libro_id = ?
            ORDER BY codigo_patrimonio ASC
        """, (lid,))
        ejemplares_lista = [
            dict(ejemplar_id=e[0], codigo_patrimonio=e[1], estado_fisico=e[2], ubicacion_estante=e[3])
            for e in cursor.fetchall()
        ]

        libros.append({
            'libro_id': f[0], 'titulo': f[1], 'autor': f[2], 'editorial': f[3],
            'anio_publicacion': f[4], 'tipo_recurso': f[5], 'archivo_pdf_url': f[6],
            'descripcion': f[7], 'total_copias': f[8], 'disponibles': f[9],
            'estante_principal': f[10],
            'portada_url': f[11] if len(f) > 11 and f[11] else None,
            'carreras_codigos': carreras_codigos,
            'carreras_ids': carreras_ids, 'ejemplares_lista': ejemplares_lista
        })

    cursor.execute("""
        SELECT e.ejemplar_id, e.codigo_patrimonio, e.ubicacion_estante, l.titulo
        FROM Ejemplares e
        JOIN Libros l ON e.libro_id = l.libro_id
        WHERE e.estado_fisico = 'MANTENIMIENTO'
        ORDER BY l.titulo ASC
    """)
    en_mantenimiento = [
        dict(ejemplar_id=r[0], codigo_patrimonio=r[1], ubicacion_estante=r[2], titulo=r[3])
        for r in cursor.fetchall()
    ]

    conn.close()
    return render_template('libros.html', libros=libros, carreras=carreras, en_mantenimiento=en_mantenimiento)

@app.route('/admin/libros/crear', methods=['GET', 'POST'])
def crear_libro():
    if request.method == 'GET':
        return redirect(url_for('listar_libros'))
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    titulo = request.form.get('titulo', '').strip()
    autor = request.form.get('autor', '').strip()
    editorial = request.form.get('editorial', '').strip()
    anio = request.form.get('anio_publicacion') or None
    tipo_recurso = request.form.get('tipo_recurso')
    archivo_pdf = request.form.get('archivo_pdf_url', '').strip() or None
    portada = request.form.get('portada_url', '').strip() or None
    descripcion = request.form.get('descripcion', '').strip()
    carreras_seleccionadas = request.form.getlist('carreras')

    if not titulo or not autor:
        flash('El título y el autor son obligatorios.', 'danger')
        return redirect(url_for('listar_libros'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Libros (titulo, autor, editorial, anio_publicacion, tipo_recurso, archivo_pdf_url, descripcion, portada_url)
        OUTPUT INSERTED.libro_id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (titulo, autor, editorial, anio, tipo_recurso, archivo_pdf, descripcion, portada))
    libro_id = cursor.fetchone()[0]

    for cid in carreras_seleccionadas:
        cursor.execute("INSERT INTO LibroCarrera (libro_id, carrera_id) VALUES (?, ?)", (libro_id, cid))

    conn.commit()
    conn.close()

    flash(f'¡Libro "{titulo}" registrado exitosamente en el catálogo!', 'success')
    return redirect(url_for('listar_libros'))

@app.route('/admin/libros/editar/<int:libro_id>', methods=['POST'])
def editar_libro(libro_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    titulo = request.form.get('titulo', '').strip()
    autor = request.form.get('autor', '').strip()
    editorial = request.form.get('editorial', '').strip()
    anio = request.form.get('anio_publicacion') or None
    tipo_recurso = request.form.get('tipo_recurso')
    archivo_pdf = request.form.get('archivo_pdf_url', '').strip() or None
    portada = request.form.get('portada_url', '').strip() or None
    descripcion = request.form.get('descripcion', '').strip()
    carreras_seleccionadas = request.form.getlist('carreras')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE Libros
        SET titulo = ?, autor = ?, editorial = ?, anio_publicacion = ?,
            tipo_recurso = ?, archivo_pdf_url = ?, descripcion = ?, portada_url = ?
        WHERE libro_id = ?
    """, (titulo, autor, editorial, anio, tipo_recurso, archivo_pdf, descripcion, portada, libro_id))

    cursor.execute("DELETE FROM LibroCarrera WHERE libro_id = ?", (libro_id,))
    for cid in carreras_seleccionadas:
        cursor.execute("INSERT INTO LibroCarrera (libro_id, carrera_id) VALUES (?, ?)", (libro_id, cid))

    conn.commit()
    conn.close()

    flash(f'¡Datos del libro "{titulo}" actualizados correctamente!', 'success')
    return redirect(url_for('listar_libros'))

@app.route('/admin/libros/ejemplares/<int:libro_id>', methods=['POST'])
def agregar_ejemplar(libro_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    codigo = request.form.get('codigo_patrimonio', '').strip().upper()
    estante = request.form.get('ubicacion_estante', '').strip()
    estado = request.form.get('estado_fisico', 'DISPONIBLE')

    if not codigo:
        flash('El código patrimonial es obligatorio.', 'warning')
        return redirect(url_for('listar_libros'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ejemplar_id FROM Ejemplares WHERE codigo_patrimonio = ?", (codigo,))
    if cursor.fetchone():
        flash(f'El código patrimonial {codigo} ya existe en el inventario.', 'danger')
        conn.close()
        return redirect(url_for('listar_libros'))

    cursor.execute("""
        INSERT INTO Ejemplares (libro_id, codigo_patrimonio, estado_fisico, ubicacion_estante)
        VALUES (?, ?, ?, ?)
    """, (libro_id, codigo, estado, estante))

    conn.commit()
    conn.close()

    flash(f'¡Copia física [{codigo}] agregada en {estante}!', 'success')
    return redirect(url_for('listar_libros'))

@app.route('/admin/ejemplares/editar/<int:ejemplar_id>', methods=['POST'])
def editar_ejemplar(ejemplar_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    codigo = request.form.get('codigo_patrimonio', '').strip().upper()
    estante = request.form.get('ubicacion_estante', '').strip()
    estado = request.form.get('estado_fisico', 'DISPONIBLE')

    conn = get_connection()
    cursor = conn.cursor()

    # Verificar que el código no esté repetido en otra copia distinta
    cursor.execute("SELECT ejemplar_id FROM Ejemplares WHERE codigo_patrimonio = ? AND ejemplar_id != ?", (codigo, ejemplar_id))
    if cursor.fetchone():
        flash(f'El código patrimonial {codigo} ya pertenece a otro ejemplar.', 'danger')
        conn.close()
        return redirect(url_for('listar_libros'))

    cursor.execute("""
        UPDATE Ejemplares
        SET codigo_patrimonio = ?, ubicacion_estante = ?, estado_fisico = ?
        WHERE ejemplar_id = ?
    """, (codigo, estante, estado, ejemplar_id))

    conn.commit()
    conn.close()

    flash(f'¡Copia [{codigo}] actualizada! Nueva ubicación: {estante}.', 'success')
    return redirect(url_for('listar_libros'))

@app.route('/admin/ejemplares/eliminar/<int:ejemplar_id>', methods=['POST'])
def eliminar_ejemplar(ejemplar_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT estado_fisico, codigo_patrimonio FROM Ejemplares WHERE ejemplar_id = ?", (ejemplar_id,))
    fila = cursor.fetchone()
    if fila:
        if fila[0] == 'PRESTADO':
            flash('No se puede eliminar una copia que se encuentra prestada actualmente.', 'danger')
        else:
            cursor.execute("DELETE FROM Prestamos WHERE ejemplar_id = ?", (ejemplar_id,))
            cursor.execute("DELETE FROM Ejemplares WHERE ejemplar_id = ?", (ejemplar_id,))
            conn.commit()
            flash(f'Copia física [{fila[1]}] eliminada del inventario.', 'info')

    conn.close()
    return redirect(url_for('listar_libros'))

@app.route('/admin/ejemplares/estado/<int:ejemplar_id>', methods=['POST'])
def cambiar_estado_ejemplar(ejemplar_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    nuevo_estado = request.form.get('nuevo_estado', 'DISPONIBLE')

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE Ejemplares SET estado_fisico = ? WHERE ejemplar_id = ?", (nuevo_estado, ejemplar_id))
    conn.commit()
    conn.close()

    if nuevo_estado == 'DISPONIBLE':
        flash('¡Ejemplar reparado y reincorporado al catálogo como DISPONIBLE!', 'success')
    else:
        flash('Ejemplar dado de BAJA definitiva del inventario.', 'info')

    return redirect(url_for('listar_libros'))

@app.route('/admin/libros/eliminar/<int:libro_id>', methods=['POST'])
def eliminar_libro(libro_id):
    if not session.get('usuario') or session['usuario']['rol'] != 'ADMIN':
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM Prestamos p
        JOIN Ejemplares e ON p.ejemplar_id = e.ejemplar_id
        WHERE e.libro_id = ? AND p.estado = 'ACTIVO'
    """, (libro_id,))
    prestamos_activos = cursor.fetchone()[0]

    if prestamos_activos > 0:
        flash('No se puede eliminar el libro: tiene copias prestadas actualmente en poder de alumnos.', 'danger')
    else:
        cursor.execute("""
            DELETE FROM Prestamos 
            WHERE ejemplar_id IN (SELECT ejemplar_id FROM Ejemplares WHERE libro_id = ?)
        """, (libro_id,))
        cursor.execute("DELETE FROM AccesosDigitales WHERE libro_id = ?", (libro_id,))
        cursor.execute("DELETE FROM Ejemplares WHERE libro_id = ?", (libro_id,))
        cursor.execute("DELETE FROM LibroCarrera WHERE libro_id = ?", (libro_id,))
        cursor.execute("DELETE FROM Libros WHERE libro_id = ?", (libro_id,))
        conn.commit()
        flash('Libro y todas sus copias eliminados limpiamente de la base de datos.', 'success')

    conn.close()
    return redirect(url_for('listar_libros'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
