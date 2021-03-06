import bson
import random
import bcrypt
import logging
import requests

from flask import g
from flask import flash
from flask import abort
from flask import url_for
from flask import request
from flask import redirect
from flask import Blueprint
from flask import render_template

from flask_login import login_user
from flask_login import logout_user
from flask_login import current_user
from flask_login import LoginManager
from flask_login import login_required

from urllib.parse import urlparse
from urllib.parse import urljoin

from econnect import app
from econnect import connect_db


main = Blueprint('main', __name__)

econnect_logger = logging.getLogger('eConnect')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
        ref_url.netloc == test_url.netloc


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'mongo_db'):
        g.mongo_client, g.mongo_db = connect_db()
    return g.mongo_db


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'mongo_db'):
        if g.mongo_client is not None:
            g.mongo_client.close()


class user_class():
    def __init__(self, username, user_id=None):
        self.is_authenticated = False
        self.is_active = True
        self.is_anonymous = False

        self.username = username
        self.user_id = user_id

        self.load()

    def check_autentication(self, username, password):
        db = get_db()
        query = {"username": username}
        print(query)
        user = db["db_users"]["users"].find_one(query)
        print(user)
        if user is not None:
            self.user_id = str(user["_id"])
            if bcrypt.checkpw(password.encode(), str(user["password"]).encode()):
                self.is_authenticated = True
                print("AUTH")
                update = {
                    "$set": {
                        "authenticated": self.is_authenticated
                    }
                }
                # user.update(update)
                db["db_users"]["users"].update_one(query, update)
                return
        self.is_authenticated = False

    def load(self):
        if self.user_id is None:
            return
        db = get_db()
        try:
            query = {"_id": bson.objectid.ObjectId(self.user_id)}
        except:
            econnect_logger.error("Error with ObjectId {}".format(self.user_id))
            return None
        print(query)
        user = db["db_users"]["users"].find_one(query)
        print(user)
        if user is None:
            return
        self.is_authenticated = user["authenticated"]
        self.username = user["username"]

    def get_id(self):
        return str(self.user_id)

    def get_brands(self):
        db = get_db()
        query = {"users": {"$elemMatch": {"$eq": bson.objectid.ObjectId(self.user_id)}}}
        brands = db["db_brands"]["brands"].find(query)
        brands_bots = {}
        for brand in brands:
            bots = []
            for bot in brand["bots"]:
                query = {"_id": bot}
                bots.append(db["db_bots"]["bots"].find_one(query))
            brands_bots[brand["_id"]] = bots
        brands.rewind()
        return brands, brands_bots

    def get_bots(self):
        db = get_db()
        query = {"owners": {"$elemMatch": {"$eq": bson.objectid.ObjectId(self.user_id)}}}
        bots = db["db_bots"]["bots"].find(query)
        return bots

    def get_facebook_auth_state(self, new=False):
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(self.user_id)}
        user = db["db_users"]["users"].find_one(query)
        state = None
        if new:
            state = str(random.randint(1000, 9999))
            update = {
                "$set": {
                    "facebook_user.facebook_auth_state": state
                }
            }
            db["db_users"]["users"].update_one(query, update)
        else:
            state = user["facebook_user"]["facebook_auth_state"]
        return state

    def get_facebook_user(self):
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(self.user_id)}
        user = db["db_users"]["users"].find_one(query)
        if user["facebook_user"] is None:
            econnect_logger.error("NOT FOUND")
            econnect_logger.error(query)
            return None
        facebook_access_token = user["facebook_user"]["facebook_access_token"]
        facebook_user_id = user["facebook_user"]["facebook_asid"]

        params = {
            "access_token": facebook_access_token
        }
        url = "https://graph.facebook.com/v2.11/{}?fields=first_name,accounts".format(facebook_user_id)
        r = requests.get(url, params=params)
        r_json = r.json()
        if "error" in r_json:
            econnect_logger.error("ERROR A")
            econnect_logger.error(r_json)
            return None

        facebook_pages = []
        if "accounts" in r_json:
            for facebook_page in r_json["accounts"]["data"]:
                if "ADMINISTER" in facebook_page["perms"]:
                    params = {
                        "access_token": facebook_access_token
                    }
                    url = "https://graph.facebook.com/v2.11/{}?fields=connected_instagram_account".format(facebook_page["id"])
                    r = requests.get(url, params=params)
                    rr_json = r.json()
                    if "error" in rr_json:
                        econnect_logger.error("ERROR B")
                        econnect_logger.error(r.text)
                    page_instagram_id = None
                    if "connected_instagram_account" in rr_json:
                        page_instagram_id = rr_json["connected_instagram_account"]["id"]
                    data = {
                        "name": facebook_page["name"],
                        "id": facebook_page["id"],
                        "instagram": page_instagram_id,
                        "subscripted_app": False
                    }
                    params = {
                        "access_token": facebook_page["access_token"]
                    }
                    url = "https://graph.facebook.com/v2.11/{}/subscribed_apps".format(facebook_page["id"])
                    r = requests.get(url, params=params)
                    rr_json = r.json()
                    print(r.text)
                    if "error" in rr_json:
                        econnect_logger.error("ERROR C")
                        econnect_logger.error(r.text)
                        return None
                    for subscription in rr_json["data"]:
                        if subscription["id"] == app.config["FB_APP_ID"]:
                            data["subscripted_app"] = True

                    facebook_pages.append(data)

        fb_user = {
            "facebook_first_name": r_json["first_name"],
            "facebook_user_id": facebook_user_id,
            "facebook_pages": facebook_pages
        }
        return fb_user

    def connect_facebook_user(self, access_token):
        # generar token de la aplicación
        params = {
            "client_id": app.config["FB_APP_ID"],
            "client_secret": app.config["FB_APP_SECRET"],
            "grant_type": "client_credentials"
        }
        url = "https://graph.facebook.com/v2.11/oauth/access_token"
        r = requests.get(url, params=params)
        r_json = r.json()
        econnect_logger.error(r_json)
        app_token = r_json["access_token"]
        # Inspect token
        params = {
            "input_token": access_token,
            "access_token": app_token
        }
        url = "https://graph.facebook.com/debug_token"
        r = requests.get(url, params=params)
        r_json = r.json()
        econnect_logger.error(r_json)
        token_user_id = r_json["data"]["user_id"]
        token_scopes = r_json["data"]["scopes"]
        token_app_id = r_json["data"]["app_id"]

        if token_app_id != app.config["FB_APP_ID"]:
            return

        # Save user token
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(self.user_id)}
        user = db["db_users"]["users"].find_one(query)
        update = {
            "$set": {
                "facebook_user": {
                    "facebook_user_id": token_user_id,
                    "facebook_access_token": access_token
                }
            }
        }
        db["db_users"]["users"].update_one(query, update)

    def connect_mercadolibre_user(self, access_token, refresh_token):
        # Inspect token
        params = {
            "access_token": access_token
        }
        url = "https://api.mercadolibre.com/users/me"
        r = requests.get(url, params=params)
        r_json = r.json()
        token_user_id = r_json["id"]
        token_user_nickname = r_json["nickname"]
        # Save user token
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(self.user_id)}
        user = db["db_users"]["users"].find_one(query)
        update = {
            "$set": {
                "mercadolibre_user": {
                    "ar": {
                        "ml_id": token_user_id,
                        "ml_nickname": token_user_nickname,
                        "ml_access_token": access_token,
                        "ml_refresh_token": refresh_token
                    }
                }
            }
        }
        db["db_users"]["users"].update_one(query, update)


@login_manager.user_loader
def load_user(user_id):
    if user_id is None:
        return None
    print("USER")
    print(user_id)
    return user_class("", user_id)


@main.route('/', methods=['GET'])
@login_required
def index():
    fuser = current_user.get_facebook_user()
    return render_template('index.html', fuser=fuser)


@main.route('/select_page/<bot_id>/<page_id>/<action>', methods=['GET'])
@login_required
def select_page(bot_id, page_id, action):
    if action not in ["select", "unselect"]:
        abort(500)
    if action == "select" and page_id == "all":
        abort(500)
    bots = current_user.get_bots()
    is_owner = False
    for bot in bots:
        if bot["_id"] == bson.objectid.ObjectId(bot_id):
            is_owner = True
    if not is_owner:
        abort(403)

    if page_id == "all" and action == "unselect":
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(bot_id)}
        update = {
            "$set": {
                "integrations.facebook.page_id": None,
                "integrations.facebook.page_access_token": None,
                "integrations.facebook.instagram_id": None,
                "integrations.facebook.user_access_token": None
            }
        }
        db["db_bots"]["bots"].update_one(query, update)
    if action == "select":
        db = get_db()
        query = {"_id": bson.objectid.ObjectId(current_user.user_id)}
        user = db["db_brands"]["brands"].find_one(query)
        if user["facebook_user"] is None:
            abort(500)
        facebook_access_token = user["facebook_user"]["facebook_access_token"]
        facebook_user_id = user["facebook_user"]["facebook_user_id"]

        # Get Page
        params = {
            "access_token": facebook_access_token
        }
        url = "https://graph.facebook.com/v2.11/{}?fields=accounts".format(facebook_user_id)
        r = requests.get(url, params=params)
        r_json = r.json()
        if "error" in r_json:
            abort(500)
        print(r.text)
        page_access_token = None
        for facebook_page in r_json["accounts"]["data"]:
            if facebook_page["id"] == page_id:
                page_access_token = facebook_page["access_token"]
                page_instagram_id = None
                break

        # Get Instagram
        params = {
            "access_token": facebook_access_token
        }
        url = "https://graph.facebook.com/v2.11/{}?fields=connected_instagram_account".format(facebook_page["id"])
        r = requests.get(url, params=params)
        rr_json = r.json()
        if "error" in rr_json:
            abort(500)
        page_instagram_id = None
        if "connected_instagram_account" in rr_json:
            page_instagram_id = rr_json["connected_instagram_account"]["id"]

        query = {"_id": bson.objectid.ObjectId(bot_id)}
        update = {
            "$set": {
                "integrations.facebook.page_id": page_id,
                "integrations.facebook.page_access_token": page_access_token,
                "integrations.facebook.instagram_id": page_instagram_id,
                "integrations.facebook.user_access_token": user["facebook_user"]["facebook_access_token"]
            }
        }
        db["db_bots"]["bots"].update_one(query, update)
    return redirect(url_for('mybots'))


@main.route('/action_to_page/<page_id>/<action>', methods=['GET'])
@login_required
def subscribe_to_page(page_id, action):
    if action not in ["subscribe", "unsubscribe"]:
        abort(500)
    db = get_db()
    query = {"_id": bson.objectid.ObjectId(current_user.user_id)}
    user = db["db_brands"]["brands"].find_one(query)
    if user["facebook_user"] is None:
        return None
    facebook_access_token = user["facebook_user"]["facebook_access_token"]
    facebook_user_id = user["facebook_user"]["facebook_user_id"]

    params = {
        "access_token": facebook_access_token
    }
    url = "https://graph.facebook.com/v2.11/{}?fields=accounts".format(facebook_user_id)
    r = requests.get(url, params=params)
    r_json = r.json()
    if "error" in r_json:
        return None
    print(r.text)
    page_access_token = None
    for facebook_page in r_json["accounts"]["data"]:
        if facebook_page["id"] == page_id:
            page_access_token = facebook_page["access_token"]

    if page_access_token is None:
        abort(500)

    params = {
        "access_token": page_access_token
    }
    url = "https://graph.facebook.com/v2.11/{}/subscribed_apps".format(page_id)
    if action == "subscribe":
        r = requests.post(url, params=params)
    elif action == "unsubscribe":
        r = requests.delete(url, params=params)
    else:
        abort(500)
    return redirect(url_for('mybots'))


@main.route('/action_to_facebook/<bot_id>/<target>/<action>', methods=['GET'])
@login_required
def integrate_bot_to(bot_id, target, action):
    db = get_db()
    query = {"_id": bson.objectid.ObjectId(bot_id)}
    # user = db["db_bots"]["bots"].find_one(query)
    # if user["facebook_user"] is None:
    #     abort(500)
    if action == "subscribe":
        update_action = True
    elif action == "unsubscribe":
        update_action = False
    else:
        abort(500)
    if target == "feed":
        update_target = "subscribed_to_feed"
    elif target == "messenger":
        update_target = "subscribed_to_messenger"
    elif target == "instagram":
        update_target = "subscribed_to_instagram"
    else:
        abort(500)
    update = {
        "$set": {
            "integrations.facebook.{}".format(update_target): update_action
        }
    }
    db["db_bots"]["bots"].update_one(query, update)
    return redirect(url_for('mybots'))


@main.route('/facebook_auth_a', methods=['GET'])
@login_required
def auth_a():
    params = {
        "client_id": app.config["FB_APP_ID"],
        "redirect_uri": "https%3A%2F%2Fconnect.eibriel.com%2Ffacebook_auth_b",
        "state": current_user.get_facebook_auth_state(True),
        "scope": "pages_messaging,read_page_mailboxes,manage_pages,publish_pages,instagram_basic,instagram_manage_comments"
    }
    url_fbauth = "https://www.facebook.com/v2.11/dialog/oauth?client_id={}&redirect_uri={}&state={}&scope={}"
    url_fbauth = url_fbauth.format(params["client_id"], params["redirect_uri"], params["state"], params["scope"])
    return redirect(url_fbauth)


@main.route('/facebook_auth_b', methods=['GET'])
@login_required
def auth_b():
    code = request.args.get('code')
    state = request.args.get('state')
    if state != current_user.get_facebook_auth_state():
        abort(500)

    # intercambiar por token de acceso
    params = {
        "client_id": app.config["FB_APP_ID"],
        "redirect_uri": "https://connect.eibriel.com/facebook_auth_b",
        "client_secret": app.config["FB_APP_SECRET"],
        "code": code
    }
    url = "https://graph.facebook.com/v2.11/oauth/access_token"
    r = requests.get(url, params=params)
    r_json = r.json()
    econnect_logger.error(r_json)
    access_token = r_json["access_token"]
    token_type = r_json["token_type"]
    # expires_in = r_json["expires_in"]
    current_user.connect_facebook_user(access_token)
    return redirect(url_for('.index'))


@main.route('/mercadolibre_auth_a', methods=['GET'])
@login_required
def mercadolibre_auth_a():
    url_mlauth = "https://auth.mercadolibre.com.ar/authorization?response_type=code&client_id={}".format(app.config["ML_APP_ID"])
    return redirect(url_mlauth)


@main.route('/mercadolibre_auth_b', methods=['GET'])
@login_required
def mercadolibre_auth_b():
    code = request.args.get('code')

    params = {
        "grant_type": "authorization_code",
        "client_id": app.config["ML_APP_ID"],
        "client_secret": app.config["ML_APP_SECRET"],
        "code": code,
        "redirect_uri": "https://connect.eibriel.com/mercadolibre_auth_b"
    }

    url = "https://api.mercadolibre.com/oauth/token"
    r = requests.get(url, params=params)
    r_json = r.json()
    access_token = r_json["access_token"]
    refresh_token = r_json["refresh_token"]
    current_user.connect_mercadolibre_user(access_token, refresh_token)
    return redirect(url_for('.index'))


@app.route("/mybrands")
@login_required
def mybrands():
    brands, brands_bots = current_user.get_brands()
    print("Brands")
    print(brands)
    print("BrandsBots")
    print(brands_bots)
    fuser = current_user.get_facebook_user()
    return render_template('mybrands.html', brands=brands, brands_bots=brands_bots, fuser=fuser)


@app.route("/mybots")
@login_required
def mybots():
    bots = current_user.get_bots()
    fuser = current_user.get_facebook_user()
    return render_template('mybots.html', bots=bots, fuser=fuser)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route("/signin", methods=['GET', 'POST'])
def signin():
    db = get_db()
    username = request.args.get('username')
    password = request.args.get('password')
    password_b = request.args.get('password_b')
    if username is not None and password is not None:
        if password != password_b:
            flash('Passwords not matching.')
            return redirect(url_for('signin'))
        db = get_db()
        query = {"username": username}
        brand = db["db_users"]["users"].find_one(query)
        if brand is not None:
            flash('Username already exists.')
            return redirect(url_for('signin'))
        hashed_password = bcrypt.hashpw(str(password).encode(), bcrypt.gensalt())
        msg_json = {
            "username": username,
            "password": hashed_password.decode("utf-8"),
            "authenticated": False,
            "facebook_user": {
                "facebook_asid": None,
                "facebook_psid": None,
                "business_token": None,
                "facebook_access_token": None,
                "facebook_auth_state": ""
            },
            "telegram_user": {
                "telegram_id": None,
                "telegram_username": None
            },
            "mercadolibre_user": {},
            "data": {}
        }
        inserted_id = db["db_users"]["users"].insert_one(msg_json).inserted_id
        flash('User correctly created')
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Here we use a class of some kind to represent and validate our
    # client-side form data. For example, WTForms is a library that will
    # handle this for us, and we use a custom LoginForm to validate.
    username = request.form.get('username')
    password = request.form.get('password')
    if username is not None:
        # Login and validate the user.
        # user should be an instance of your `User` class
        user = user_class(username)
        user.check_autentication(username, password)
        if user.is_authenticated:
            login_user(user)

            flash('Logged in successfully.')

            next = request.args.get('next')
            # is_safe_url should check if the url is safe for redirects.
            # See http://flask.pocoo.org/snippets/62/ for an example.
            if not is_safe_url(next):
                return abort(400)

            return redirect(next or url_for('main.index'))
        else:
            flash('Authentication Error.')
    return render_template('login.html', username=username)


@app.route("/privacy")
def privacy():
    return render_template('privacy.html')
