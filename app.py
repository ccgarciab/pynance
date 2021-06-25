import os
import re

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

from helpers import apology, login_required, lookup, usd, credit_verify


# Ensure environment variable is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd


# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure the necessary tables are created and related
db.execute("""CREATE TABLE IF NOT EXISTS 'users' (
    'id' INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    'username' TEXT NOT NULL,
    'hash' TEXT NOT NULL,
    'cash' NUMERIC NOT NULL DEFAULT 10000.00 )""")

db.execute("""CREATE TABLE IF NOT EXISTS 'transactions' (
    'id_tran' INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    'id_user' INTEGER NOT NULL,
    'symbol' TEXT NOT NULL,
    'shares' INTEGER NOT NULL,
    'price' NUMERIC NOT NULL,
    'time' TEXT NOT NULL,
    FOREIGN KEY(id_user) REFERENCES users(id))""")

db.execute("""CREATE TABLE IF NOT EXISTS 'stocks' (
    'id_stock' INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    'id_user' INTEGER NOT NULL,
    'symbol' TEXT NOT NULL,
    'amount' INTEGER NOT NULL,
    FOREIGN KEY(id_user) REFERENCES users(id))""")

# Regex to compare a new password, to ensure it has min 8 chars, a number, a lowercase and an uppercase
good_pass = re.compile(r"^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{8,30}$")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get the symbols of all the stocks owned by the user
    rows = db.execute("SELECT symbol, amount FROM stocks WHERE id_user=:u_id", u_id=session["user_id"])

    # Variable to record the total holdings of user
    total = 0

    # for every row (dict) of owned symbols
    for row in rows:

        # We'll query the current price of the matching stock, and NOT yield until we get it
        result = lookup(row["symbol"])
        while not result:
            result = lookup(row["symbol"])

        # Store the price of a single share, and the value of all the stock in the same row (dict)
        row["price"] = result["price"]
        row["total"] = row["amount"] * row["price"]

        # The value of this stock sums up to the total holdings
        total += row["total"]

    # Sum to the value of all the stocks the cash, to get the total holdings
    cash = db.execute("SELECT cash FROM users WHERE id=:u_id", u_id=session["user_id"])[0]["cash"]
    total += cash
    return render_template("index.html", rows=rows, cash=cash, total=total)


@app.route("/account")
@login_required
def account():
    """Show page with utilities related to the user"""

    # Render a page with several forms that POST to different URLs
    return render_template("account.html")


@app.route("/add_cash", methods=["POST"])
@login_required
def add_cash():
    """URL and function to process a cash depositusing a credit card"""

    # Assign alias to the method to make its name shorter
    rfg = request.form.get

    # Look up the data submited by the user
    cash, credit, password = rfg("cash"), rfg("credit card"), rfg("password")

    # Ensure the user filled the form
    if not (cash and credit and password):
        return apology("fill info")

    # Ensure the credit card number has nothing different from numbers, spaces and hyphens
    if re.fullmatch(r"^(?!.*[^0-9- ]).+$", credit):

        # Transform the credit card string into an integer
        credit = int("".join(re.findall(r"\d+", credit)))

        # Verify it is a valid VISA, AMEX or MASTERCARD number
        if credit_verify(credit):

            # Validate user's password
            h = db.execute("SELECT hash FROM users WHERE id=:u_id", u_id=session["user_id"])[0]["hash"]
            if check_password_hash(h, password):

                # Add the cash deposited to the user's old cash
                o_cash = db.execute("SELECT cash FROM users WHERE id=:u_id", u_id=session["user_id"])[0]["cash"]
                db.execute("UPDATE users SET cash=:ncash WHERE id=:u_id", ncash=o_cash + int(cash), u_id=session["user_id"])
                message = "Cash deposit complete"

            else:
                message = "Incorrect password"

        else:
            message = "Invalid card number"

    else:
        message = "Please only use numbers, spaces and hyphens when typing a card number"

    # Go back to the account page (origin of the request) and inform about the status of the operation
    flash(message)
    return redirect("/account")


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # The user got here through a POST request (form)
    if request.method == "POST":

        # Store the submited info
        symbol = request.form.get("symbol")
        try:

            # Make the shares string into a number
            shares = int(request.form.get("shares"))
        except ValueError:

            # Ensure an integer number of shares
            return apology("Numeric shares only")
        except TypeError:

            # Ensure the field wasn't left empty (NoneType isn't a valid int() argument)
            return apology("Fill shares")

        # Ensure a symbol was provided
        if not symbol:
            return apology("not symbol")

        # Ensure a positive amount of shares
        if not 0 < shares:
            return apology("not positive shares")

        # Get the price of the symbol's matching stock
        result = lookup(symbol)

        # If the API doesn't answer, the symbol is (probably) invalid. Otherwise, store it.
        if not result:
            return apology("symbol 404")

        symbol, price = result["symbol"], result["price"]

        # Ensure the user can afford the purchase
        u_id = session["user_id"]
        cash = db.execute("SELECT cash FROM users WHERE id=:u_id", u_id=u_id)[0]["cash"]
        if cash < (price * shares):
            return apology("u poor")

        # If the user has enough money, substract the cost from their cash reserves
        db.execute("UPDATE users SET cash=:ncash WHERE id=:u_id",
                   ncash=cash - (price * shares), u_id=u_id)

        # Register a transaction
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""INSERT INTO transactions (id_user, symbol, shares, price, time) VALUES
            (:id_user, :symbol, :shares, :price, :time)""", id_user=u_id, symbol=symbol, shares=shares, price=price, time=t)

        stock = db.execute("SELECT id_stock FROM stocks WHERE id_user=:u_id AND symbol=:symbol", u_id=u_id, symbol=symbol)

        if not stock:
            # If the user doesn't own share of this stock, register that now he does
            db.execute("""INSERT INTO stocks (id_user, symbol, amount) VALUES
                (:u_id, :symbol, :amount)""", u_id=u_id, symbol=symbol, amount=shares)

        else:
            # If the user had shares of this company, add to this amount the recently purchased stock
            stock = stock[0]["id_stock"]
            old_amount = db.execute("SELECT amount FROM stocks WHERE id_stock=:stock", stock=stock)[0]["amount"]
            db.execute("UPDATE stocks SET amount=:namount WHERE id_stock=:stock",
                       namount=old_amount + shares, stock=stock)

        ending = "s" if shares > 1 else ""
        flash(f"You have successfully purchased {shares} {symbol} share{ending}")
        return redirect("/")

    # User reached this URL via GET (link, redirect)
    else:
        return render_template("buy.html")


@app.route("/change_pass", methods=["POST"])
@login_required
def change_pass():
    """URL and function to process a password change request"""

    # Assign alias to the method to make its name shorter
    rfg = request.form.get

    # store the old password, the new one, and the confirmation of the new one (last one avoids typos)
    o_pass, n_pass, conf = rfg("password"), rfg("new password"), rfg("confirmation")

    # Ensure the user has provided the information
    if not (o_pass and n_pass and conf):
        return apology("fill info", 403)

    # Check that the provided (current) password is valid. Compare it to hash
    u_id = session["user_id"]
    h = db.execute("SELECT hash FROM users WHERE id=:u_id", u_id=u_id)[0]["hash"]
    if check_password_hash(h, o_pass):

        # Ensure the user has typed the new password correctly 2 times
        if n_pass == conf:

            # Ensure the new password complies with our password policy
            if good_pass.fullmatch(n_pass):

                # Store the hash based in the new password
                db.execute("UPDATE users SET hash=:n_pass WHERE id=:u_id", n_pass=generate_password_hash(n_pass), u_id=u_id)
                message = "Password correctly updated"

            else:
                message = "Passwords must have at least 8 characters and include numbers, uppercase and lowercase letters"

        else:
            message = "New password doesn't match the confirmation"

    else:
        message = "Incorrect password"

    flash(message)
    return redirect("/account")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # Transaction data has been stored, so just pass the query to the template
    trans = db.execute("SELECT symbol, shares, price, time FROM transactions WHERE id_user=:u_id", u_id=session["user_id"])
    return render_template("history.html", trans=trans)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # User reached route via POST (form)
    if request.method == "POST":

        # Ensure user provided a symbol to quote
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("not symbol")

        # Use API to lookup it's current price
        result = lookup(symbol)

        # If the API doesn't answer, the symbol is (probably) invalid
        if not result:
            return apology("symbol 404")

        # Pass the result of the lookup to the template
        return render_template("quoted.html", result=result)

    # User reached route via GET (link, redirect)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Adds a user (and their password) to the database"""

    # User got here via POST (form)
    if request.method == "POST":

        # Assign alias to the method to make its name shorter
        rfg = request.form.get

        # Store the desired username and password, and the password confirmation used to avoid typos
        username, password, confirmation = rfg("username"), rfg("password"), rfg("confirmation")

        # Ensure the user filed the form
        if not (username and password and confirmation):
            return apology("fill info")

        # Ensure the user typed the same password twice
        if password != confirmation:
            return apology("not confirmed")

        # Ensure the password complies with our password policy
        if not good_pass.fullmatch(password):
            flash("Password must be at least 8 letters, include a number, an uppercase and a lowercase letter")
            return redirect("/register")

        # Search for the username in the database, to ensure we don't have duplictes
        rows = db.execute("SELECT * FROM users WHERE username = :u_name", u_name=username)
        if rows:
            return apology("already registered")

        # If everything is in order, add the user to the database
        db.execute("INSERT INTO users (username, hash) VALUES (:u_name, :p_word)",
                   u_name=username, p_word=generate_password_hash(password))
        flash('You were successfully registered')
        return redirect("/")

    # User reached the route via GET (link, redirect)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # Store the current user, so we don't have to aces the dict ach time
    u_id = session["user_id"]

    # The user reached the route via POST (form)
    if request.method == "POST":

        # Store the symbol of the shares the user want to sell, and the amount. Ensure the user filled the form
        symbol, shares = request.form.get("symbol"), request.form.get("shares")
        if not (symbol and shares):
            return apology("fill info")

        # Ensure the user is selling an integer amount of shares
        try:
            shares = int(shares)
        except ValueError:
            return apology("enter an integer")

        # Ensure the user is selling a positive amount of shares
        if not 0 < shares:
            return apology("positive numbers only")

        # Make sure the user has an amount of stocks registered and this amount is not 0
        available = db.execute("SELECT amount FROM stocks WHERE id_user=:u_id AND symbol=:symbol", u_id=u_id, symbol=symbol)
        if not (available and available[0]["amount"]):
            return apology("somehow no stocks")

        # Ensure the user is not selling more shares than they have
        available = available[0]["amount"]
        if available < shares:
            return apology("you don't have that many")

        # Get the date and time of the transaction
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # We'll query the current price of the matching stock, and NOT yield until we get it
        price = lookup(symbol)
        while not price:
            price = lookup(symbol)
        price = price["price"]

        # Get the current amount of cash the user has
        old_cash = db.execute("SELECT cash FROM users WHERE id=:u_id", u_id=u_id)[0]["cash"]

        # Register the transaction and add the money from the sell to their existences
        db.execute("""INSERT INTO transactions (id_user, symbol, shares, price, time) VALUES
            (:id_user, :symbol, :sh, :price, :t)""", id_user=u_id, symbol=symbol, sh=(-shares), price=price, t=t)
        db.execute("UPDATE users SET cash=:cash WHERE id=:u_id", cash=old_cash + (shares * price), u_id=u_id)

        if available == shares:
            # If the user sells all their shares for this stock, delete the register of them having stocks of this company
            db.execute("DELETE FROM stocks WHERE id_user=:u_id AND symbol=:symbol", u_id=u_id, symbol=symbol)

        else:
            # Otherwise, just substract from their stocks the amount they sold
            db.execute("UPDATE stocks SET amount=:amount WHERE id_user=:u_id AND symbol=:symbol",
                       amount=available - shares, u_id=u_id, symbol=symbol)

        ending = "s" if shares > 1 else ""
        flash(f"You successfully sold {shares} {symbol} share{ending}")
        return redirect("/")

    # The user reached the route via GET (link, redirect)
    else:
        stocks = db.execute("SELECT symbol FROM stocks WHERE id_user=:u_id", u_id=u_id)
        return render_template("sell.html", stocks=stocks)


def errorhandler(e):
    """Handle error"""
    return apology(e.name, e.code)


# listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
