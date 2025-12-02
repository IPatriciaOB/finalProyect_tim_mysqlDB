from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from datetime import timedelta 

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    apellido = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    direccion = db.Column(db.String(200))
    telefono = db.Column(db.String(20))
    role = db.Column(db.String(20), default='cliente') 
    is_active = db.Column(db.Boolean, default=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    # Usamos Numeric para dinero, coincide con DECIMAL en SQL
    precio = db.Column(db.Numeric(10, 2), nullable=False) 
    stock = db.Column(db.Integer, default=0)
    imagen = db.Column(db.String(255)) 

class Order(db.Model):
    # 'order' es palabra reservada en SQL, SQLAlchemy lo maneja bien si usamos backticks en SQL manual
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Pendiente de envío')
    total = db.Column(db.Numeric(10, 2), nullable=False)
    
    tracking_number = db.Column(db.String(100))
    shipping_company = db.Column(db.String(100))

    # Relaciones
    items = db.relationship('OrderItem', backref='order', lazy=True)
    user = db.relationship('User', backref='orders')

    # === LÓGICA DE FECHA ESTIMADA ===
    @property
    def delivery_window(self):
        """Calcula fecha min y max de entrega (3 a 5 días después de la compra)"""
        if self.date:
            start = self.date + timedelta(days=3)
            end = self.date + timedelta(days=5)
            return start, end
        return None

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product_name = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)

class PaymentMethod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_type = db.Column(db.String(20))
    card_holder = db.Column(db.String(100))
    masked_number = db.Column(db.String(20))
    
    # Relación inversa para acceder desde el usuario (user.payment_methods)
    user = db.relationship('User', backref='payment_methods')

class Courier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)

