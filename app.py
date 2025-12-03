from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from models import db, User, Product, Order, OrderItem, PaymentMethod, Courier
from collections import Counter
from werkzeug.utils import secure_filename
import os
import io
import openpyxl
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mi_secreto_super_seguro'

# --- CONFIGURACIÓN DE SUBIDA DE IMÁGENES ---
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'img')

# --- CONFIGURACIÓN DB ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:admin@localhost/melodias_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- RUTAS PÚBLICAS ---
@app.route('/')
def index():
    productos = Product.query.all()
    return render_template('index.html', productos=productos)

@app.route('/help')
def help():
    return render_template('help.html')

# --- CARRITO DE COMPRAS ---
# --- RUTA: DETALLE DEL PRODUCTO ---
@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    return render_template('product_detail.html', product=product)

# --- RUTA: AGREGAR AL CARRITO ---
@app.route('/add_to_cart/<int:product_id>', methods=['GET', 'POST'])
def add_to_cart(product_id):
    quantity = 1
    if request.method == 'POST':
        try:
            quantity = int(request.form.get('quantity', 1))
        except ValueError:
            quantity = 1
    
    product = Product.query.get_or_404(product_id)
    
    if 'cart' not in session:
        session['cart'] = []
        
    current_in_cart = session['cart'].count(product_id)
    
    if (current_in_cart + quantity) > product.stock:
        flash(f'No hay suficiente stock. Disponibles: {product.stock}, Tienes en carrito: {current_in_cart}', 'warning')
        return redirect(url_for('product_detail', id=product_id))

    # 3. Agregar al carrito (Session)
    for _ in range(quantity):
        session['cart'].append(product_id)
        
    session.modified = True
    flash(f'Se agregaron {quantity} unidades de {product.nombre} al carrito.', 'success')
    return redirect(url_for('index'))

@app.route('/cart')
def view_cart():
    if current_user.is_authenticated and current_user.role != 'cliente':
        flash('Los administradores no compran, gestionan.', 'info')
        return redirect(url_for('admin_dashboard'))

    cart_ids = session.get('cart', [])
    if not cart_ids:
        return render_template('cart.html', items=[], total=0, is_empty=True)
    
    counts = Counter(cart_ids)
    productos_db = Product.query.filter(Product.id.in_(list(counts.keys()))).all()
    
    items = []
    total_general = 0
    for p in productos_db:
        cantidad = counts[p.id]
        subtotal = p.precio * cantidad
        total_general += subtotal
        items.append({'product': p, 'cantidad': cantidad, 'subtotal': subtotal})
    user_payments = []
    if current_user.is_authenticated:
        from models import PaymentMethod 
        user_payments = PaymentMethod.query.filter_by(user_id=current_user.id).all()

    return render_template('cart.html', items=items, total=total_general, is_empty=False, payment_methods=user_payments)

@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    if 'cart' in session:
        session['cart'] = [id for id in session['cart'] if id != product_id]
        session.modified = True
    flash('Producto eliminado.', 'info')
    return redirect(url_for('view_cart'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    payment_method_id = request.form.get('payment_method_id')
    if not payment_method_id:
        flash('Por favor selecciona un método de pago para continuar.', 'danger')
        return redirect(url_for('view_cart'))

    cart_ids = session.get('cart', [])
    if not cart_ids: 
        return redirect(url_for('index'))
    
    counts = Counter(cart_ids)
    productos_db = Product.query.filter(Product.id.in_(list(counts.keys()))).all()
    
    total_order = 0
    
    # Verificar Stock
    for p in productos_db:
        if p.stock < counts[p.id]:
            flash(f'Stock insuficiente para: {p.nombre}. Disponibles: {p.stock}', 'danger')
            return redirect(url_for('view_cart'))
        total_order += p.precio * counts[p.id]
        
    # Crear Pedido
    new_order = Order(user_id=current_user.id, total=total_order, status='Pendiente de envío')
    db.session.add(new_order)
    db.session.commit() 
    
    # Crear Items y Restar Stock
    for p in productos_db:
        qty = counts[p.id]
        p.stock -= qty 
        item = OrderItem(
            order_id=new_order.id, 
            product_id=p.id, 
            product_name=p.nombre, 
            quantity=qty, 
            price=p.precio
        )
        db.session.add(item)
        
    db.session.commit() 
    session.pop('cart', None) 
    flash('¡Pedido realizado con éxito!', 'success')
    return render_template('order_success.html')

# CANCELAR PEDIDO
@app.route('/cancel_order/<int:order_id>')
@login_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    
    if order.user_id != current_user.id:
        flash('No tienes permiso para modificar este pedido.', 'danger')
        return redirect(url_for('profile'))
    
    if order.status != 'Pendiente de envío':
        flash('No se puede cancelar el pedido porque ya fue procesado o enviado.', 'warning')
        return redirect(url_for('profile'))
    
    for item in order.items:
        producto = Product.query.get(item.product_id)
        if producto:
            producto.stock += item.quantity
            
    order.status = 'Cancelado'
    db.session.commit()
    
    flash('Pedido cancelado correctamente. El stock ha sido restaurado.', 'info')
    return redirect(url_for('profile'))

# --- PERFIL ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        user = current_user
        user.nombre = request.form.get('nombre')
        user.apellido = request.form.get('apellido')
        user.direccion = request.form.get('direccion')
        user.telefono = request.form.get('telefono')
        
        new_pass = request.form.get('password')
        conf_pass = request.form.get('confirm_password')
        
        if new_pass:
            if new_pass == conf_pass:
                user.password = generate_password_hash(new_pass)
                flash('Contraseña actualizada', 'success')
            else:
                flash('Las contraseñas no coinciden', 'danger')
                return redirect(url_for('profile'))
        
        db.session.commit()
        flash('Información actualizada', 'success')
        return redirect(url_for('profile'))

    active_orders = []
    cancelled_orders = []
    
    if current_user.role == 'cliente':
        all_orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.date.desc()).all()
        for o in all_orders:
            if o.status == 'Cancelado':
                cancelled_orders.append(o)
            else:
                active_orders.append(o)
            
    return render_template('profile.html', user=current_user, active_orders=active_orders, cancelled_orders=cancelled_orders)

# --- RUTA ACERCA DE NOSOTROS ---
@app.route('/about')
def about():
    return render_template('about.html')

# --- AUTH ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            if not user.is_active:
                flash('Cuenta desactivada. Contacte al admin.', 'danger')
                return redirect(url_for('login'))
            
            session.pop('cart', None) 
            
            login_user(user)
            flash(f'Bienvenido, {user.nombre}', 'success')

            if user.role in ['admin', 'empleado']: 
                return redirect(url_for('admin_dashboard'))
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page) 
                
            return redirect(url_for('index'))

        else:
            flash('Credenciales incorrectas', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash('El email ya está registrado.', 'danger')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(request.form.get('password'))
        new_user = User(
            nombre=request.form.get('nombre'), 
            apellido=request.form.get('apellido'),
            email=email, 
            password=hashed_pw,
            direccion=request.form.get('direccion'), 
            telefono=request.form.get('telefono'),
            role='cliente'
        )
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash('Registro exitoso', 'success')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada.', 'info')
    return redirect(url_for('index'))

# --- ADMIN ---
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role == 'cliente': 
        return redirect(url_for('index'))
    return render_template('admin.html', 
                           productos=Product.query.all(), 
                           pedidos=Order.query.order_by(Order.date.desc()).all(), 
                           usuarios=User.query.all())

@app.route('/admin/product/add', methods=['POST'])
@login_required
def add_product():
    if current_user.role not in ['admin', 'empleado']: 
        return redirect(url_for('index'))
    
    try:
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock'))
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion') 
        
        imagen_nombre = "guitarra.jpg" 
        
        if 'imagen' in request.files:
            file = request.files['imagen']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                imagen_nombre = filename
        # ------------------------
        
        new_prod = Product(
            nombre=nombre, 
            precio=precio,
            stock=stock, 
            descripcion=descripcion or "Nuevo producto", 
            imagen=imagen_nombre
        )
        db.session.add(new_prod)
        db.session.commit()
        flash('Producto agregado correctamente', 'success')
    except Exception as e:
        flash(f'Error al agregar: {str(e)}', 'danger')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/product/edit/<int:id>', methods=['POST'])
@login_required
def edit_product(id):
    if current_user.role not in ['admin', 'empleado']: return redirect(url_for('index'))
    
    prod = Product.query.get_or_404(id)
    prod.nombre = request.form.get('nombre')
    prod.descripcion = request.form.get('descripcion')
    prod.precio = float(request.form.get('precio'))
    prod.stock = int(request.form.get('stock'))
    prod.imagen = request.form.get('imagen')
    
    db.session.commit()
    flash('Inventario actualizado', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/product/delete/<int:id>')
@login_required
def delete_product(id):
    if current_user.role not in ['admin', 'empleado']: return redirect(url_for('index'))
    prod = Product.query.get_or_404(id)
    try:
        db.session.delete(prod)
        db.session.commit()
        flash('Producto eliminado', 'warning')
    except:
        db.session.rollback()
        flash('No se puede eliminar: el producto está en pedidos históricos.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/order/update/<int:id>', methods=['POST'])
@login_required
def update_order(id):
    # Validar permisos
    if current_user.role not in ['admin', 'empleado']: 
        return redirect(url_for('index'))
    
    order = Order.query.get_or_404(id)
    new_status = request.form.get('status')
    
    # --- LÓGICA DE GENERACIÓN AUTOMÁTICA ---
    if new_status == 'Enviado' and order.status != 'Enviado':
        
        couriers = Courier.query.all()
        if couriers:
            selected_courier = random.choice(couriers)
            order.shipping_company = selected_courier.name
        else:
            order.shipping_company = "Transporte Interno"

        random_digits = ''.join(random.choices(string.digits, k=8))
        order.tracking_number = f"TRK-{random_digits}"
        
        flash(f'Pedido enviado. Se asignó guía: {order.tracking_number} ({order.shipping_company})', 'success')

    order.status = new_status
    db.session.commit()
    
    if new_status != 'Enviado':
        flash(f'Pedido #{id} actualizado a {new_status}', 'info')
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/report')
@login_required
def download_report():
    if current_user.role not in ['admin', 'empleado']: return redirect(url_for('index'))
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["ID Pedido", "Cliente", "Total", "Estado", "Fecha"])
    
    for o in Order.query.all():
        ws.append([o.id, o.user.email, o.total, o.status, o.date])
        
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return send_file(out, download_name="reporte_ventas.xlsx", as_attachment=True)

@app.route('/deactivate_account')
@login_required
def deactivate_account():
    current_user.is_active = False
    db.session.commit()
    
    logout_user()
    
    flash('Tu cuenta ha sido cerrada correctamente. Esperamos verte pronto.', 'info')
    return redirect(url_for('index'))

@app.route('/profile/payment/add', methods=['POST'])
@login_required
def add_payment_method():
    number = request.form.get('card_number')
    holder = request.form.get('card_holder')
    ctype = request.form.get('card_type')
    
    masked = f"**** **** **** {number[-4:]}"
    
    new_pm = PaymentMethod(
        user_id=current_user.id,
        card_type=ctype,
        card_holder=holder,
        masked_number=masked
    )
    db.session.add(new_pm)
    db.session.commit()
    
    flash('Método de pago agregado correctamente.', 'success')
    return redirect(url_for('profile') + '#payment-methods')

@app.route('/profile/payment/delete/<int:id>')
@login_required
def delete_payment_method(id):
    pm = PaymentMethod.query.get_or_404(id)
    if pm.user_id != current_user.id:
        flash('Acción no autorizada', 'danger')
        return redirect(url_for('profile'))
        
    db.session.delete(pm)
    db.session.commit()
    flash('Método de pago eliminado.', 'warning')
    return redirect(url_for('profile') + '#payment-methods')

# --- CREAR EMPLEADO (SOLO ADMIN) ---
@app.route('/admin/user/create', methods=['POST'])
@login_required
def create_employee():
    if current_user.role != 'admin': return redirect(url_for('index'))
    
    email = request.form.get('email')
    if User.query.filter_by(email=email).first():
        flash('El email ya existe.', 'danger')
        return redirect(url_for('admin_dashboard'))

    hashed_pw = generate_password_hash(request.form.get('password'))
    new_emp = User(
        nombre=request.form.get('nombre'),
        apellido=request.form.get('apellido'),
        email=email,
        password=hashed_pw,
        direccion=request.form.get('direccion'),
        telefono=request.form.get('telefono'),
        role='empleado', 
        is_active=True
    )
    db.session.add(new_emp)
    db.session.commit()
    flash('Empleado creado correctamente.', 'success')
    return redirect(url_for('admin_dashboard') + '#usrs')

# --- ACTIVAR/DESACTIVAR USUARIO ---
@app.route('/admin/user/toggle/<int:id>')
@login_required
def toggle_user_status(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    
    user = User.query.get_or_404(id)
    
    if user.id == current_user.id:
        flash('No puedes desactivar tu propia cuenta.', 'warning')
        return redirect(url_for('admin_dashboard') + '#usrs')
        
    user.is_active = not user.is_active
    db.session.commit()
    
    estado = "activado" if user.is_active else "desactivado"
    flash(f'Usuario {user.email} {estado}.', 'info')
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    app.run(debug=True)