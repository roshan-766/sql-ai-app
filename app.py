import streamlit as st
import os
from dotenv import load_dotenv
from openrouter import OpenRouter

load_dotenv()
st.set_page_config(page_title="SQL Chat-Bot",layout="wide")

st.sidebar.title("Menu")
page=st.sidebar.radio("Go to:",["Home","Connection"])


if page == "Home":
    st.title("SQL AI Chat-Bot")
    st.title("AAKASH")
    st.write("Welcome ! Type Your Promt Below.")

    user_prompt = st.text_area("Enter Your Prompt")

    if(st.button("Generate", type="primary")):
        api_key=os.getenv("OPENROUTER_API_KEY")
        if  not user_prompt:
            st.warning("Please Enter a Prompt First!")
       
        elif (api_key):
            try:
                with OpenRouter(api_key=api_key)as client:
                    
                    response=client.chat.send(
                        model="nvidia/nemotron-3-ultra-550b-a55b:free",
                        messages=[
                            {"role":"system","content":"You are a SQL generator. Return ONLY the raw SQL query on a single line. "
                                    "Do NOT use markdown, do NOT use triple backticks (```), no line breaks, "
                                    "and no conversational text."},
                            {"role":"user","content": user_prompt}
                        ]
                    )
                    st.subheader("Generated SQL Query:")
                    st.code(response.choices[0].message.content,language="sql")
            except Exception as e:
                st.error(f"Error:{e}")
            