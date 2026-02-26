from flask import Flask, render_template, request, redirect, session, Response, send_file
import sqlite3
from datetime import date
import csv
from io import StringIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

app = Flask(__name__)
app.secret_key = "quickcart_secret"

# ---------------- DATABASE INIT ----------------
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            quantity INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            quantity INTEGER,
            total REAL,
            sale_date TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "1234":
            session["user"] = "admin"
            return redirect("/")
        return "Invalid Credentials"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")

# ---------------- DASHBOARD ----------------
@app.route("/")
def home():
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()

    total_products = len(products)
    total_stock = sum(p[3] for p in products)
    total_value = sum(p[2] * p[3] for p in products)
    low_stock_count = len([p for p in products if p[3] <= 5])

    today = str(date.today())
    cursor.execute("SELECT SUM(total), COUNT(*) FROM sales WHERE sale_date=?", (today,))
    data = cursor.fetchone()

    today_sales = data[0] if data[0] else 0
    total_transactions = data[1] if data[1] else 0

    conn.close()

    return render_template(
        "index.html",
        products=products,
        total_products=total_products,
        total_stock=total_stock,
        total_value=total_value,
        today_sales=today_sales,
        total_transactions=total_transactions,
        low_stock_count=low_stock_count,
        user=session["user"]
    )

# ---------------- ADD PRODUCT ----------------
@app.route("/add", methods=["POST"])
def add_product():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (name, price, quantity) VALUES (?, ?, ?)",
        (request.form["name"], request.form["price"], request.form["quantity"])
    )
    conn.commit()
    conn.close()
    return redirect("/")

# ---------------- SELL PRODUCT ----------------
@app.route("/sell/<int:id>", methods=["POST"])
def sell_product(id):
    qty = int(request.form["sell_quantity"])

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("SELECT price, quantity FROM products WHERE id=?", (id,))
    product = cursor.fetchone()

    if product and product[1] >= qty:
        new_qty = product[1] - qty
        total = product[0] * qty

        cursor.execute("UPDATE products SET quantity=? WHERE id=?", (new_qty, id))
        cursor.execute(
            "INSERT INTO sales (product_id, quantity, total, sale_date) VALUES (?, ?, ?, ?)",
            (id, qty, total, str(date.today()))
        )
        conn.commit()

    conn.close()
    return redirect("/")

# ---------------- SALES HISTORY ----------------
@app.route("/sales")
def sales_history():
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sales.id, products.name, sales.quantity, sales.total, sales.sale_date
        FROM sales
        JOIN products ON sales.product_id = products.id
        ORDER BY sales.id DESC
    """)

    sales = cursor.fetchall()

    cursor.execute("SELECT SUM(total), COUNT(*) FROM sales")
    summary = cursor.fetchone()

    total_revenue = summary[0] if summary[0] else 0
    total_transactions = summary[1] if summary[1] else 0

    conn.close()

    return render_template("sales.html",
        sales=sales,
        total_revenue=total_revenue,
        total_transactions=total_transactions
    )

# ---------------- DELETE SALE ----------------
@app.route("/delete_sale/<int:id>", methods=["POST"])
def delete_sale(id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("SELECT product_id, quantity FROM sales WHERE id=?", (id,))
    sale = cursor.fetchone()

    if sale:
        cursor.execute("UPDATE products SET quantity = quantity + ? WHERE id=?", (sale[1], sale[0]))
        cursor.execute("DELETE FROM sales WHERE id=?", (id,))
        conn.commit()

    conn.close()
    return redirect("/sales")

# ---------------- RESET TODAY ----------------
@app.route("/reset_today", methods=["POST"])
def reset_today():
    today = str(date.today())
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sales WHERE sale_date=?", (today,))
    conn.commit()
    conn.close()
    return redirect("/")

# ---------------- CSV EXPORT ----------------
@app.route("/export_sales")
def export_sales():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT sales.id, products.name, sales.quantity, sales.total, sales.sale_date
        FROM sales
        JOIN products ON sales.product_id = products.id
    """)
    sales = cursor.fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["Sale ID", "Product", "Quantity", "Total", "Date"])
    cw.writerows(sales)

    output = Response(si.getvalue(), mimetype="text/csv")
    output.headers["Content-Disposition"] = "attachment; filename=sales_report.csv"
    return output

# ---------------- INVOICE PDF ----------------
@app.route("/invoice/<int:sale_id>")
def generate_invoice(sale_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT products.name, sales.quantity, sales.total, sales.sale_date
        FROM sales
        JOIN products ON sales.product_id = products.id
        WHERE sales.id=?
    """, (sale_id,))
    sale = cursor.fetchone()
    conn.close()

    if not sale:
        return "Invoice not found"

    filename = f"invoice_{sale_id}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    elements.append(Paragraph("<b>QuickCart POS Invoice</b>", styles["Title"]))
    elements.append(Spacer(1, 20))

    data = [
        ["Product", sale[0]],
        ["Quantity", sale[1]],
        ["Total Amount", f"₹{sale[2]}"],
        ["Date", sale[3]]
    ]

    table = Table(data)
    table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))

    elements.append(table)
    doc.build(elements)

    return send_file(filename, as_attachment=True)

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)