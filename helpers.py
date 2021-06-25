import csv
import os
import urllib.request

from flask import redirect, render_template, request, session
from functools import wraps


def apology(message, code=400):
    """Render message as an apology to user."""
    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [("-", "--"), (" ", "-"), ("_", "__"), ("?", "~q"),
                         ("%", "~p"), ("#", "~h"), ("/", "~s"), ("\"", "''")]:
            s = s.replace(old, new)
        return s
    return render_template("apology.html", top=code, bottom=escape(message)), code


def credit_verify(creditCard):
    """checks if a credit card number is a valid AMEX, VISA or MASTERCARD card"""
    evens, odds, n_odds = [], [], []
    digits = 0

    while creditCard:
        d = creditCard % 10
        if digits % 2:
            odds.append(d % 10)
            d *= 2
            if 9 < d:
                n_odds.append(d % 10)
                d //= 10
            n_odds.append(d)
        else:
            evens.append(d)
        creditCard //= 10
        digits += 1

    if digits != 13 and digits != 15 and digits != 16:
        return False

    if(len(evens) > len(odds)):
        first, second = evens[len(evens) - 1], odds[len(odds) - 1]
    else:
        first, second = odds[len(odds) - 1], evens[len(evens) - 1]

    amex = digits == 15 and first == 3 and (second == 4 or second == 7)
    visa = first = 4 and (digits == 13 or digits == 16)
    master = first == 5 and (0 < second and second < 6) and digits == 16
    if not (amex or visa or master):
        return False
    valid = ((sum(evens) + sum(n_odds)) % 10) == 0
    return (True if valid else False)


def login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/0.12/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


def lookup(symbol):
    """Look up quote for symbol."""

    # Reject symbol if it starts with caret
    if symbol.startswith("^"):
        return None

    # Reject symbol if it contains comma
    if "," in symbol:
        return None

    # Query Alpha Vantage for quote
    # https://www.alphavantage.co/documentation/
    try:

        # GET CSV
        url = f"https://www.alphavantage.co/query?apikey={os.getenv('API_KEY')}&datatype=csv&function=TIME_SERIES_INTRADAY&interval=1min&symbol={symbol}"
        webpage = urllib.request.urlopen(url)

        # Parse CSV
        datareader = csv.reader(webpage.read().decode("utf-8").splitlines())

        # Ignore first row
        next(datareader)

        # Parse second row
        row = next(datareader)

        # Ensure stock exists
        try:
            price = float(row[4])
        except:
            return None

        # Return stock's name (as a str), price (as a float), and (uppercased) symbol (as a str)
        return {
            "price": price,
            "symbol": symbol.upper()
        }

    except:
        return None


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"
