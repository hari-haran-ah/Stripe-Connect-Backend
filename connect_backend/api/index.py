import os
import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# 🔐 Load Stripe Secret Key
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# 🏪 Zara Connected Account ID
# 🏪 Zara Connected Account ID
ZARA_ACCOUNT_ID = os.getenv("ZARA_ACCOUNT_ID")

app = FastAPI()


# Allow frontend to call backend
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
def home():
    return {"message": "Server is running"}

from typing import List

# ----------- REQUEST MODELS -----------

class CartItem(BaseModel):
    name: str
    price: float
    quantity: int
    image: str

class CheckoutRequest(BaseModel):
    items: List[CartItem]
    customer_id: str = None

class PortalRequest(BaseModel):
    customer_id: str

# ----------- CREATE CHECKOUT SESSION -----------

@app.post("/create-checkout-session")
def create_checkout_session(data: CheckoutRequest):
    try:
        line_items = []
        for item in data.items:
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item.name,
                        'images': [item.image] if item.image else [],
                    },
                    'unit_amount': int(item.price * 100),
                },
                'quantity': item.quantity,
            })

        platform_fee = 10000

        session_args = {
            'payment_method_types': ['card'],
            'line_items': line_items,
            'mode': 'payment',
            'invoice_creation': {"enabled": True},
            'payment_intent_data': {
                'application_fee_amount': platform_fee,
                'transfer_data': {
                    'destination': ZARA_ACCOUNT_ID,
                },
            },
            'success_url': f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            'cancel_url': f"{FRONTEND_URL}/",
        }

        if data.customer_id:
            session_args['customer'] = data.customer_id
        else:
            session_args['customer_creation'] = 'always'

        session = stripe.checkout.Session.create(**session_args)

        return {"sessionId": session.id, "url": session.url}

    except Exception as e:
        print(f"Error creating session: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


# ----------- RETRIEVE SESSION (For Customer ID) -----------

@app.get("/checkout-session")
def get_checkout_session(sessionId: str):
    try:
        session = stripe.checkout.Session.retrieve(sessionId)
        return {"customer_id": session.customer}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------- CREATE PORTAL SESSION -----------

@app.post("/create-portal-session")
def create_portal_session(data: PortalRequest):
    try:
        session = stripe.billing_portal.Session.create(
            customer=data.customer_id,
            return_url=f"{FRONTEND_URL}/success",
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------- STRIPE WEBHOOK (IMPORTANT) -----------

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        print("❌ Webhook Error: Invalid payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        print("❌ Webhook Error: Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]
        print(f"💰 Payment Succeeded (Intent): {payment_intent['id']}")
    
    elif event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print(f"✅ Checkout Session Completed: {session['id']}")

    return {"status": "success"}

