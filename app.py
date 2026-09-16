from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import requests
from openai import OpenAI
from dotenv import load_dotenv
import json
import tempfile
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

# Load environment variables
load_dotenv()

# Flask app
app = Flask(__name__)
CORS(app)


import mimetypes
from werkzeug.utils import secure_filename
import hashlib

# Configure static folder for media
app.config['MEDIA_FOLDER'] = os.path.join(os.getcwd(), 'static', 'media')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Ensure media directories exist
os.makedirs(os.path.join(app.config['MEDIA_FOLDER'], 'audio'), exist_ok=True)
os.makedirs(os.path.join(app.config['MEDIA_FOLDER'], 'images'), exist_ok=True)
os.makedirs(os.path.join(app.config['MEDIA_FOLDER'], 'videos'), exist_ok=True)
os.makedirs(os.path.join(app.config['MEDIA_FOLDER'], 'documents'), exist_ok=True)
# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://urduxx:shahbazcool@whatappweb.rjnnppd.mongodb.net/")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['whatsappweb']
users_collection = db['users']
messages_collection = db['messages']

# Environment variables
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")

# IMPORTANT: Print config on startup to verify
print("\n" + "="*50)
print("🔧 CONFIGURATION CHECK")
print("="*50)
print(f"WHATSAPP_TOKEN exists: {bool(WHATSAPP_TOKEN)}")
print(f"WHATSAPP_TOKEN length: {len(WHATSAPP_TOKEN) if WHATSAPP_TOKEN else 0}")
print(f"WHATSAPP_PHONE_NUMBER_ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"WHATSAPP_VERIFY_TOKEN: {WHATSAPP_VERIFY_TOKEN}")
print(f"OPENAI_API_KEY exists: {bool(os.getenv('OPENAI_API_KEY'))}")
print(f"MONGO_URI configured: {bool(MONGO_URI)}")
print("="*50 + "\n")

SYSTEM_PROMPT = """
You are the official AI assistant for **UrduX**, a modern AI company building smart multi-lingual Chatbots and Voice Bots for Urdu & English audiences.

CRITICAL ALWAYS RESPOND IN EGLISH OR URDU NO OTHER LANGUAGE.

🎯 **Core Rule**
- Keep answers short, friendly and clear — **2–3 lines max**, always concise and to the point.

💬 **Interaction Style**
- Speak like a warm, helpful team member — friendly, natural, and human-like.
- Use emojis wisely to keep the vibe light 😊✨  
- Vary your tone: sometimes informative, sometimes casual, sometimes ending with a light question.
- Stay interactive — but don’t overdo follow-up questions.

🚫 **Restrictions (Made lighter & user-friendly)**
- Only answer questions related to **UrduX** (services, team, products, pricing, features, support).
- If asked about unrelated topics, competitors, politics, other companies, or general knowledge:
  → Reply politely: **"I can only help with UrduX services, but happy to guide you about our AI solutions!"**

😊 **Allowed**
- Greetings, small talk, casual chat
- Explaining UrduX features, services, benefits, pricing, and support
- Friendly conversation while staying on topic

---

## 🏢 **About UrduX**
- **Founded:** June 2024  
- **Headquarters:** Islamabad (fully remote team across Pakistan)  
- **Mission:** Bring cutting-edge AI voice tech to 220M+ Urdu speakers  

## 👥 **Leadership**
- **CEO:** Dr. Mehreen Alam — 20+ years in AI & NLP  
- **AI Team Lead:** Ali Tajir — expert in speech recognition & LLM systems  
- **Full-Stack Team Lead:** Haris Ali — builds scalable backend systems  

## 🤖 **Services We Offer**
- AI Voice Bots (Urdu/English)
- Smart Chatbots with code-switching
- Appointment & Lead Qualification Bots
- CRM, ERP & API Integrations
- Analytics & Reporting Dashboards

## 🌟 **Key Features**
- Multi-lingual support (Urdu + English)
- High accuracy with local dialects
- Fully customizable solutions
- Secure, encrypted data workflows
- Works for small startups & large enterprises

## 🏭 **Industries We Serve**
Healthcare, Education, Banking, Real Estate, Retail & Service Sectors

## 📞 **Contact**
- **Email:** connect@urdux.tech  
- **Website:** https://urdux.tech  
- **Support:** Available through email & chat  

---

🎯 **Final Behavior Guidelines**
- Always answer in **2–3 clear, friendly, well-formatted lines**.
- Be conversational, interactive, and warm — never robotic.
- Use light emojis to enhance clarity and friendliness, not to overwhelm.
- Give precise, helpful answers about UrduX services.

"""

# -------------------------
# MongoDB Helper Functions
# -------------------------
def get_or_create_user(phone_number, name=None):
    """Get existing user or create new one"""
    user = users_collection.find_one({"phone_number": phone_number})
    
    if not user:
        user_data = {
            "phone_number": phone_number,
            "name": name or phone_number,
            "first_contact": datetime.utcnow(),
            "last_message": datetime.utcnow(),
            "unread_count": 0,
            "status": "active"
        }
        result = users_collection.insert_one(user_data)
        user_data['_id'] = result.inserted_id
        return user_data
    else:
        # Update last message time
        users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_message": datetime.utcnow()}}
        )
        return user

def save_message(phone_number, message_type, content, direction, media_url=None, status="sent"):
    """Save message to database"""
    message_data = {
        "phone_number": phone_number,
        "message_type": message_type,
        "content": content,
        "direction": direction,  # 'incoming' or 'outgoing'
        "media_url": media_url,
        "status": status,
        "timestamp": datetime.utcnow(),
        "read": False if direction == "incoming" else True
    }
    
    result = messages_collection.insert_one(message_data)
    
    # Update user's unread count if incoming
    if direction == "incoming":
        users_collection.update_one(
            {"phone_number": phone_number},
            {"$inc": {"unread_count": 1}}
        )
    
    return result.inserted_id

# -------------------------
# Transcription helper
# -------------------------
def transcribe_audio_with_whisper(file_path):
    """Use OpenAI Whisper to transcribe audio file"""
    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
                language="ur",
            )
        return {"transcription": transcript}
    except Exception as e:
        return {"error": str(e)}

# -------------------------
# Chat Bot API
# -------------------------
@app.route("/api/chat", methods=["POST"])
def chat_bot():
    """Handle chat bot conversations"""
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        conversation_history = data.get("history", [])
        
        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        
        # Build messages for OpenAI
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add conversation history
        for msg in conversation_history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        # Get response from OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        bot_response = response.choices[0].message.content
        
        return jsonify({
            "success": True,
            "response": bot_response
        })
        
    except Exception as e:
        print(f"❌ Chat bot error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# -------------------------
# Voice Bot API (OpenAI Realtime) - UPDATED WITH SYSTEM PROMPT
# -------------------------

@app.route("/api/voice/session", methods=["POST"])

def create_voice_session():
    """Create OpenAI Realtime API session token with UrduX system instructions"""

    try:

        # Create ephemeral token for client-side Realtime API with instructions

        response = client.sessions.create(

            model="gpt-4o-mini-realtime-preview-2024-12-17",

            voice="alloy",

            instructions=SYSTEM_PROMPT,  # ADD SYSTEM PROMPT HERE

            modalities=["text", "audio"],

            temperature=0.7

        )
        return jsonify({

            "success": True,

            "session_id": response.id,

            "client_secret": response.client_secret.value,

            "instructions": SYSTEM_PROMPT  # Also send to frontend for reference

        })

    except Exception as e:

        print(f"❌ Voice session error: {str(e)}")

        return jsonify({"error": str(e)}), 500



@app.route("/api/voice/token", methods=["GET"])

def get_voice_token():

    """Get OpenAI API key and system prompt for Realtime API (client-side usage)"""

    try:

        return jsonify({

            "success": True,

            "api_key": os.getenv("OPENAI_API_KEY"),

            "instructions": SYSTEM_PROMPT  # Send system prompt to frontend

        })

    except Exception as e:

        return jsonify({"error": str(e)}), 500



@app.route("/api/voice/instructions", methods=["GET"])

def get_voice_instructions():

    """Get system instructions for voice bot"""

    return jsonify({

        "success": True,

        "instructions": SYSTEM_PROMPT

    })


# -------------------------
# WhatsApp Bot APIs
# -------------------------
def download_whatsapp_media(media_id, phone_number, media_type):
    """Download media from WhatsApp and save locally"""
    try:
        # Get media URL from WhatsApp
        media_info_resp = requests.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10
        )
        media_info = media_info_resp.json()
        download_url = media_info.get("url")
        
        if not download_url:
            print(f"❌ No download URL for media {media_id}")
            return None
        
        # Download the media file
        media_resp = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=30
        )
        
        if media_resp.status_code != 200:
            print(f"❌ Failed to download media: {media_resp.status_code}")
            return None
        
        # Determine file extension
        content_type = media_resp.headers.get('Content-Type', '')
        extension = mimetypes.guess_extension(content_type) or ''
        
        # Special handling for common types
        if 'audio/ogg' in content_type or 'audio/opus' in content_type:
            extension = '.ogg'
        elif 'image/jpeg' in content_type:
            extension = '.jpg'
        elif 'image/png' in content_type:
            extension = '.png'
        elif 'video/mp4' in content_type:
            extension = '.mp4'
        elif 'application/pdf' in content_type:
            extension = '.pdf'
        
        # Create filename: timestamp_hash.extension
        timestamp = int(datetime.utcnow().timestamp())
        file_hash = hashlib.md5(media_id.encode()).hexdigest()[:8]
        filename = f"{timestamp}_{file_hash}{extension}"
        
        # Determine subfolder based on media type
        subfolder = media_type + 's' if not media_type.endswith('s') else media_type
        if subfolder == 'audios':
            subfolder = 'audio'
        
        # Create phone-specific directory
        phone_dir = os.path.join(app.config['MEDIA_FOLDER'], subfolder, phone_number)
        os.makedirs(phone_dir, exist_ok=True)
        
        # Save file
        file_path = os.path.join(phone_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(media_resp.content)
        
        # Return relative URL path for database
        relative_path = f"/static/media/{subfolder}/{phone_number}/{filename}"
        
        print(f"✅ Media saved: {relative_path}")
        return relative_path
        
    except Exception as e:
        print(f"❌ Error downloading media: {str(e)}")
        return None
    
def send_whatsapp_message(to, message):
    """Send text message to WhatsApp user"""
    print(f"\n{'='*50}")
    print(f"📤 ATTEMPTING TO SEND WHATSAPP MESSAGE")
    print(f"{'='*50}")
    print(f"To: {to}")
    print(f"Message: {message[:100]}..." if len(message) > 100 else f"Message: {message}")
    print(f"Phone Number ID: {WHATSAPP_PHONE_NUMBER_ID}")
    print(f"Token exists: {bool(WHATSAPP_TOKEN)}")
    
    if not WHATSAPP_TOKEN:
        print("❌ ERROR: WHATSAPP_TOKEN is not set!")
        return {"error": "WhatsApp token not configured"}
    
    if not WHATSAPP_PHONE_NUMBER_ID:
        print("❌ ERROR: WHATSAPP_PHONE_NUMBER_ID is not set!")
        return {"error": "WhatsApp phone number ID not configured"}
    
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }
    
    try:
        print(f"🌐 Sending POST request to: {url}")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response_data = response.json()
        
        print(f"📊 Response Status: {response.status_code}")
        print(f"📊 Response Data: {json.dumps(response_data, indent=2)}")
        
        if response.status_code == 200:
            print("✅ Message sent successfully!")
            # Save outgoing message to database
            save_message(to, "text", message, "outgoing")
        else:
            print(f"❌ Failed to send message. Status: {response.status_code}")
            print(f"❌ Error: {response_data}")
        
        print(f"{'='*50}\n")
        return response_data
        
    except requests.exceptions.Timeout:
        error_msg = "Request timeout - WhatsApp API took too long to respond"
        print(f"❌ {error_msg}")
        print(f"{'='*50}\n")
        return {"error": error_msg}
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        print(f"❌ {error_msg}")
        print(f"{'='*50}\n")
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"❌ {error_msg}")
        print(f"{'='*50}\n")
        return {"error": error_msg}

def send_whatsapp_audio(to, audio_url):
    """Send audio message to WhatsApp user"""
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"link": audio_url}
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print("❌ Error sending audio:", response.text)
    else:
        save_message(to, "audio", "Audio message", "outgoing", media_url=audio_url)
    return response.json()

@app.route("/whatsapp", methods=["GET", "POST"])
def whatsapp_webhook():
    """WhatsApp webhook for receiving and sending messages"""
    if request.method == "GET":
        # Webhook verification
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        print(f"🔐 Webhook verification attempt")
        print(f"Received token: {verify_token}")
        print(f"Expected token: {WHATSAPP_VERIFY_TOKEN}")
        
        if verify_token == WHATSAPP_VERIFY_TOKEN:
            print("✅ Verification successful!")
            return challenge
        
        print("❌ Verification failed - token mismatch")
        return "Invalid verification token", 403
    
    if request.method == "POST":
        data = request.get_json()
        
        print(f"\n{'='*50}")
        print(f"📥 INCOMING WHATSAPP WEBHOOK")
        print(f"{'='*50}")
        print(f"Raw data: {json.dumps(data, indent=2)}")
        
        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])
            
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                
                # Check if this is a status update instead of a message
                if not messages and value.get("statuses"):
                    print("ℹ️ Received status update, ignoring")
                    continue
                
                for message in messages:
                    phone_number = message.get("from")
                    msg_type = message.get("type")
                    message_id = message.get("id")
                    
                    print(f"\n📩 Message Details:")
                    print(f"   From: {phone_number}")
                    print(f"   Type: {msg_type}")
                    print(f"   ID: {message_id}")
                    
                    # Get or create user
                    user = get_or_create_user(phone_number)
                    
                    # Handle text messages
                    if msg_type == "text":
                        message_text = message.get("text", {}).get("body", "")
                        print(f"   Text: {message_text}")
                        
                        if message_text:
                            # Save incoming message
                            save_message(phone_number, "text", message_text, "incoming")
                            
                            # Get bot response using OpenAI
                            try:
                                print(f"\n🤖 Getting AI response...")
                                
                                response = client.chat.completions.create(
                                    model="gpt-4o-mini",
                                    messages=[
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {"role": "user", "content": message_text}
                                    ],
                                    temperature=0.7,
                                    max_tokens=500
                                )
                                
                                bot_response = response.choices[0].message.content
                                print(f"✅ AI Response generated: {bot_response[:100]}...")
                                
                                # Send response
                                send_result = send_whatsapp_message(phone_number, bot_response)
                                
                                if "error" in send_result:
                                    print(f"❌ Failed to send WhatsApp message: {send_result['error']}")
                                
                            except Exception as e:
                                error_msg = f"Error getting bot response: {str(e)}"
                                print(f"❌ {error_msg}")
                                send_whatsapp_message(
                                    phone_number,
                                    "Sorry, I encountered an error. Please try again."
                                )
                    
                    # Handle audio messages
                    # Handle audio messages
                    elif msg_type == "audio":
                        audio_obj = message.get("audio")
                        if audio_obj:
                            media_id = audio_obj.get("id")
                            mime_type = audio_obj.get("mime_type", "audio/ogg")
                            print(f"🔊 Received audio media id: {media_id}, mime_type: {mime_type}")
                            
                            try:
                                # Download and save audio
                                saved_path = download_whatsapp_media(media_id, phone_number, "audio")
                                
                                if saved_path:
                                    # Save incoming audio message with local path
                                    save_message(phone_number, "audio", "Voice message", "incoming", media_url=saved_path)
                                    
                                    # Get full path for transcription
                                    full_path = os.path.join(os.getcwd(), saved_path.lstrip('/'))
                                    
                                    print(f"📁 Audio saved at: {full_path}")
                                    print(f"📁 File exists: {os.path.exists(full_path)}")
                                    
                                    # Transcribe the audio
                                    trans_result = transcribe_audio_with_whisper(full_path)
                                    
                                    if "error" in trans_result:
                                        print(f"❌ Transcription error: {trans_result['error']}")
                                        bot_response = "Sorry, I couldn't understand the audio. Could you please type your message or send a clearer audio?"
                                    else:
                                        user_text = trans_result.get("transcription", "")
                                        print(f"📝 Transcription: {user_text}")
                                        
                                        if user_text.strip():
                                            # Get bot response
                                            response = client.chat.completions.create(
                                                model="gpt-4o-mini",
                                                messages=[
                                                    {"role": "system", "content": SYSTEM_PROMPT},
                                                    {"role": "user", "content": user_text}
                                                ],
                                                temperature=0.7,
                                                max_tokens=500
                                            )
                                            bot_response = response.choices[0].message.content
                                        else:
                                            bot_response = "I received your voice message but couldn't hear any speech. Could you try again?"
                                    
                                    send_whatsapp_message(phone_number, bot_response)
                                else:
                                    print("❌ Failed to download audio")
                                    save_message(phone_number, "audio", "Voice message (download failed)", "incoming")
                                    send_whatsapp_message(phone_number, "Sorry, I couldn't download your voice message. Please try again.")
                                    
                            except Exception as e:
                                print(f"❌ Error processing audio: {str(e)}")
                                import traceback
                                print(f"Traceback: {traceback.format_exc()}")
                                save_message(phone_number, "audio", "Voice message (error)", "incoming")
                                send_whatsapp_message(phone_number, "Sorry, there was an error processing your voice message. Please try again or type your message.")
                    
                    # Handle image messages
                    elif msg_type == "image":
                        image_obj = message.get("image")
                        if image_obj:
                            media_id = image_obj.get("id")
                            caption = image_obj.get("caption", "")
                            print(f"📷 Received image media id: {media_id}")
                            
                            try:
                                # Download and save image
                                saved_path = download_whatsapp_media(media_id, phone_number, "image")
                                
                                if saved_path:
                                    content = f"📷 Image{': ' + caption if caption else ''}"
                                    save_message(phone_number, "image", content, "incoming", media_url=saved_path)
                                    send_whatsapp_message(phone_number, "📷 Thanks for the image! How can I help you?")
                                else:
                                    save_message(phone_number, "image", "Image (download failed)", "incoming")
                                    
                            except Exception as e:
                                print(f"❌ Error processing image: {str(e)}")
                                save_message(phone_number, "image", "Image (error)", "incoming")
                    
                    # Handle video messages
                    elif msg_type == "video":
                        video_obj = message.get("video")
                        if video_obj:
                            media_id = video_obj.get("id")
                            caption = video_obj.get("caption", "")
                            print(f"🎥 Received video media id: {media_id}")
                            
                            try:
                                # Download and save video
                                saved_path = download_whatsapp_media(media_id, phone_number, "video")
                                
                                if saved_path:
                                    content = f"🎥 Video{': ' + caption if caption else ''}"
                                    save_message(phone_number, "video", content, "incoming", media_url=saved_path)
                                    send_whatsapp_message(phone_number, "🎥 Got your video! What can I do for you?")
                                else:
                                    save_message(phone_number, "video", "Video (download failed)", "incoming")
                                    
                            except Exception as e:
                                print(f"❌ Error processing video: {str(e)}")
                                save_message(phone_number, "video", "Video (error)", "incoming")
                    
                    # Handle document messages
                    elif msg_type == "document":
                        doc_obj = message.get("document")
                        if doc_obj:
                            media_id = doc_obj.get("id")
                            doc_name = doc_obj.get("filename", "document")
                            print(f"📄 Received document media id: {media_id}, name: {doc_name}")
                            
                            try:
                                # Download and save document
                                saved_path = download_whatsapp_media(media_id, phone_number, "document")
                                
                                if saved_path:
                                    save_message(phone_number, "document", f"📄 {doc_name}", "incoming", media_url=saved_path)
                                    send_whatsapp_message(phone_number, f"📄 Received {doc_name}!")
                                else:
                                    save_message(phone_number, "document", f"Document: {doc_name} (download failed)", "incoming")
                                    
                            except Exception as e:
                                print(f"❌ Error processing document: {str(e)}")
                                save_message(phone_number, "document", f"Document: {doc_name} (error)", "incoming")
                    
                    else:
                        print(f"   ℹ️ Unsupported message type: {msg_type}")
            
            print(f"{'='*50}\n")
                    
        except Exception as e:
            print(f"❌ Error in webhook: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
        
        return "OK", 200
# -------------------------
# Manual WhatsApp Send API (for testing from frontend)
# -------------------------
@app.route("/api/whatsapp/send", methods=["POST"])
def send_whatsapp_manual():
    """Manually send WhatsApp message (for testing)"""
    try:
        data = request.get_json()
        phone = data.get("phone")
        message = data.get("message")
        
        if not phone or not message:
            return jsonify({"error": "Phone and message required"}), 400
        
        # Format phone number (remove + if present)
        phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        
        print(f"📤 Manual send request - Phone: {phone}, Message: {message}")
        
        result = send_whatsapp_message(phone, message)
        
        return jsonify({
            "success": "error" not in result,
            "result": result
        })
        
    except Exception as e:
        print(f"❌ Send WhatsApp error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# -------------------------
# Dashboard Routes
# -------------------------
@app.route("/")
def home():
    """Serve dashboard"""
    return render_template("dashboard.html")

@app.route("/api/users", methods=["GET"])
def get_users():
    """Get all users sorted by last message"""
    try:
        users = list(users_collection.find().sort("last_message", -1))
        
        # Convert ObjectId to string
        for user in users:
            user['_id'] = str(user['_id'])
            user['first_contact'] = user['first_contact'].isoformat()
            user['last_message'] = user['last_message'].isoformat()
        
        return jsonify(users)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/<phone_number>", methods=["GET"])
def get_messages(phone_number):
    """Get all messages for a specific user"""
    try:
        messages = list(messages_collection.find(
            {"phone_number": phone_number}
        ).sort("timestamp", 1))
        
        # Convert ObjectId to string and format dates
        for msg in messages:
            msg['_id'] = str(msg['_id'])
            msg['timestamp'] = msg['timestamp'].isoformat()
        
        # Mark messages as read
        messages_collection.update_many(
            {"phone_number": phone_number, "direction": "incoming"},
            {"$set": {"read": True}}
        )
        
        # Reset unread count
        users_collection.update_one(
            {"phone_number": phone_number},
            {"$set": {"unread_count": 0}}
        )
        
        return jsonify(messages)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/send-message", methods=["POST"])
def api_send_message():
    """Send message from dashboard"""
    try:
        data = request.get_json()
        phone_number = data.get("phone_number")
        message = data.get("message")
        
        if not phone_number or not message:
            return jsonify({"error": "Missing phone_number or message"}), 400
        
        result = send_whatsapp_message(phone_number, message)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# Health Check
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "services": {
            "chat_bot": "available",
            "voice_bot": "available",
            "whatsapp_bot": "available" if WHATSAPP_TOKEN else "not configured",
            "dashboard": "available",
            "database": "connected" if mongo_client else "disconnected"
        },
        "config": {
            "whatsapp_token_set": bool(WHATSAPP_TOKEN),
            "whatsapp_phone_id_set": bool(WHATSAPP_PHONE_NUMBER_ID),
            "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
            "mongo_connected": bool(mongo_client)
        }
    }), 200

@app.route("/api/test-audio/<phone_number>", methods=["GET"])
def test_audio(phone_number):
    """Test endpoint to check audio files"""
    audio_dir = os.path.join(app.config['MEDIA_FOLDER'], 'audio', phone_number)
    
    if not os.path.exists(audio_dir):
        return jsonify({"error": "No audio directory found", "path": audio_dir}), 404
    
    files = os.listdir(audio_dir)
    file_info = []
    
    for file in files:
        file_path = os.path.join(audio_dir, file)
        file_info.append({
            "name": file,
            "size": os.path.getsize(file_path),
            "url": f"/static/media/audio/{phone_number}/{file}"
        })
    
    return jsonify({
        "directory": audio_dir,
        "files": file_info,
        "count": len(files)
    })
# -------------------------
# Run App
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8003))
    print(f"\n{'='*50}")
    print(f"🚀 Starting Enhanced Multi-Bot Server on port {port}...")
    print(f"📱 WhatsApp configured: {bool(WHATSAPP_TOKEN)}")
    print(f"🤖 OpenAI configured: {bool(os.getenv('OPENAI_API_KEY'))}")
    print(f"💾 MongoDB connected: {bool(mongo_client)}")
    print(f"📊 Dashboard available at: http://localhost:{port}/")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=port, debug=True)