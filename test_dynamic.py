from flask import Flask, request, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
import os

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///default.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class TestItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))

engines = {}

def get_tenant_engine(tenant):
    if tenant not in engines:
        engines[tenant] = create_engine(f"sqlite:///{tenant}.db")
    return engines[tenant]

# Custom bind for FSA 3
class DynamicSession(db.session.__class__):
    def get_bind(self, mapper=None, clause=None, **kw):
        tenant = getattr(g, 'tenant', None)
        if tenant:
            return get_tenant_engine(tenant)
        return super().get_bind(mapper=mapper, clause=clause, **kw)

db.session = db.create_scoped_session(options={'class_': DynamicSession})

@app.route("/<tenant>/add/<name>")
def add(tenant, name):
    g.tenant = tenant
    db.create_all() # Creates tables in the tenant DB
    item = TestItem(name=name)
    db.session.add(item)
    db.session.commit()
    return f"Added {name} to {tenant}"

@app.route("/<tenant>/list")
def list_items(tenant):
    g.tenant = tenant
    items = TestItem.query.all()
    return ", ".join([i.name for i in items])

if __name__ == "__main__":
    with app.app_context():
        pass
    # Just run a simulated request
    with app.test_request_context("/tenant1/add/item1"):
        print(app.dispatch_request())
    with app.test_request_context("/tenant2/add/item2"):
        print(app.dispatch_request())
    with app.test_request_context("/tenant1/list"):
        print("Tenant1:", app.dispatch_request())
    with app.test_request_context("/tenant2/list"):
        print("Tenant2:", app.dispatch_request())
    
    # Clean up
    if os.path.exists("tenant1.db"): os.remove("tenant1.db")
    if os.path.exists("tenant2.db"): os.remove("tenant2.db")
    if os.path.exists("default.db"): os.remove("default.db")
