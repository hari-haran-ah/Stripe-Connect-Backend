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

def calculate_platform_fee(amount):
    if amount <= 10000:
        return 1000
    elif amount <= 20000:
        return 1500
    else:
        return 2000

@app.get("/")
def home():
    return {"message": "Server is running"}

from typing import List , Optional

# ----------- REQUEST MODELS -----------
class CartItem(BaseModel):
    name: str
    price: float
    quantity: int
    image: Optional[str] = None

class CheckoutRequest(BaseModel):
    items: List[CartItem]
    customer_id: Optional[str] = None

class PortalRequest(BaseModel):
    customer_id: str

# ----------- CREATE CHECKOUT SESSION -----------

@app.post("/create-checkout-session")
def create_checkout_session(data: CheckoutRequest):
    try:
        line_items = []
        total_amount = 0
        for item in data.items:
            unit_amount = int(item.price * 100)
            quantity = item.quantity
            total_amount += unit_amount * quantity
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

        platform_fee = calculate_platform_fee(total_amount)

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
# ----------- STRIPE WEBHOOK (FULL CONNECT SUPPORT) -----------

@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            endpoint_secret
        )
    except ValueError as e:
        print("❌ Webhook Error: Invalid payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        print("❌ Webhook Error: Invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    connected_account = event.get("account", "platform")

    print("========================================")
    print(f"🔔 Webhook Event Received")
    print(f"📌 Event Type: {event['type']}")
    print(f"🏪 Account ID: {connected_account}")
    print("========================================")
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        print("✅ Checkout Session Completed")
        print(f"Session ID: {session['id']}")
        print(f"Customer ID: {session.get('customer')}")
        print(f"Amount Total: {session.get('amount_total')}")
        print(f"Payment Intent: {session.get('payment_intent')}")

        # TODO: Save order in database


    # Payment succeeded
    elif event["type"] == "payment_intent.succeeded":
        payment_intent = event["data"]["object"]

        print("💰 Payment Intent Succeeded")
        print(f"PaymentIntent ID: {payment_intent['id']}")
        print(f"Amount: {payment_intent['amount']}")
        print(f"Currency: {payment_intent['currency']}")
        print(f"Customer: {payment_intent.get('customer')}")

        # TODO: Update payment status in database


    # Charge succeeded
    elif event["type"] == "charge.succeeded":
        charge = event["data"]["object"]

        print("💳 Charge Succeeded")
        print(f"Charge ID: {charge['id']}")
        print(f"Amount: {charge['amount']}")
        print(f"Transfer: {charge.get('transfer')}")

        # TODO: Save charge info


    # Transfer created (Connect transfer to Zara account)
    elif event["type"] == "transfer.created":
        transfer = event["data"]["object"]

        print("🔁 Transfer Created to Connected Account")
        print(f"Transfer ID: {transfer['id']}")
        print(f"Amount: {transfer['amount']}")
        print(f"Destination: {transfer['destination']}")

        # TODO: Save transfer record


    # Transfer paid
    elif event["type"] == "transfer.paid":
        transfer = event["data"]["object"]

        print("🏦 Transfer Paid")
        print(f"Transfer ID: {transfer['id']}")
        print(f"Amount: {transfer['amount']}")

        # TODO: Confirm transfer


    else:
        print(f"ℹ️ Unhandled event type: {event['type']}")

    # Step 4: Return success response
    return {"status": "success"}
