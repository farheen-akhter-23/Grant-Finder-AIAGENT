from quart import Quart, render_template, request, jsonify, session
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
import os
import sys
from dotenv import load_dotenv
from pydantic import SecretStr
from agent import main as run_automation
import asyncio
import json

# Set your Gemini API key
load_dotenv()
GOOGLE_API_KEY = SecretStr(os.getenv('GEMINI_API_KEY'))

# Create the LangChain chat model
llm = ChatGoogleGenerativeAI(
    model='gemini-2.0-flash-exp', 
    api_key=GOOGLE_API_KEY
)

app = Quart(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(42))

@app.route("/")
async def index():
    session.clear()
    session["history"] = [{"role": "ai", "content": "Hi! What type of grant are you looking for?"}]
    session["step"] = 1
    return await render_template("index.html")

@app.route("/history", methods=["GET"])
async def history():
    return jsonify(session.get("history", []))

@app.route("/chat", methods=["POST"])
async def chat():
    user_input = (await request.get_json())["message"]
    history = session.get("history", [])
    step = session.get("step", 1)

    history.append({"role": "user", "content": user_input})

    if step == 1:
        session["grant_type"] = user_input

        extract_prompt = f"""
        Extract keywords and a deadline from this grant description:
        "{user_input}"

        Respond in JSON with keys: keyword, deadline.
        If not available, return null for that field.
        """

        extract_response = await llm.ainvoke([HumanMessage(content=extract_prompt)])
        try:
            json_str = extract_response.content.strip().strip('`')
            if json_str.startswith('json'):
                json_str = json_str[4:].strip()
            extracted = json.loads(json_str)

            keyword = extracted.get("keyword")
            deadline = extracted.get("deadline")
        except Exception as e:
            print(f"Extraction error: {e}")
            keyword = deadline = None

        if keyword: session["keyword"] = keyword
        if deadline: session["deadline"] = deadline

        if not keyword:
            session["step"] = 2
            ai_response = "Any keywords to include?"
        elif not deadline:
            session["step"] = 3
            ai_response = "Do you have a deadline?"
        else:
            session["step"] = 4
            ai_response = "Searching now..."
            search_prompt = f"""
                In the database https://spin.infoedglobal.com find the ID, Link, and Deadline for {session.get('grant_type')} grants
                with keywords: {session.get('keyword')},
                deadline (Format 12-Mar-2026): {session.get('deadline')}.
                Then locate the funding
                scroll down to the bottom of the page and select all for the items per page
                collect all the data from the grants on the page
            """
            asyncio.create_task(run_automation(search_prompt))

    elif step == 2:
        session["keyword"] = user_input
        session["step"] = 3
        ai_response = "Do you have a deadline?"

    elif step == 3:
        session["deadline"] = user_input
        session["step"] = 4
        ai_response = "Searching now..."
        search_prompt = f"""
            In the database https://spin.infoedglobal.com {session.get('grant_type')} grants
            with keywords: {session.get('keyword')},
            deadline (Format 12-Mar-2026): {session.get('deadline')}.
            Click locate funding scroll to the bottom of the page
            Change the ammount of items per page to all
            Scroll back to the top of the page
        """
        asyncio.create_task(run_automation(search_prompt))

    else:
        messages = [
            AIMessage(content="Respond with 10 words or less. Be concise.")
        ] + [
            HumanMessage(content=msg["content"]) if msg["role"] == "user" else AIMessage(content=msg["content"])
            for msg in history
        ]
        response = await llm.ainvoke(messages)
        ai_response = response.content

    history.append({"role": "ai", "content": ai_response})
    session["history"] = history

    return jsonify({"response": ai_response})


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
