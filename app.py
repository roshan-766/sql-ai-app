import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openrouter import OpenRouter
from sqlalchemy import create_engine, inspect

load_dotenv()
st.set_page_config(page_title="SQL Assistant", layout="wide")

# Custom CSS for clean UI styling
st.markdown(
    """
    <style>
    .stButton>button {
        border-radius: 4px;
        padding: 4px 12px;
    }
    .stCodeBlock {
        border-radius: 4px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# SESSION STATE INITIALIZATION
# ---------------------------------------------------------
defaults = {
    "messages": [],
    "db_engine": None,
    "db_type": "None",
    "saved_connections": [],
    "pending_redirect": None,
    "current_page": "Home",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def get_database_schema_context(engine):
    """Returns database schema information formatted for the LLM context."""
    if not engine:
        return "No database engine connected."
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        schema_text = ""
        for table in tables:
            columns = inspector.get_columns(table)
            col_names = [f"{col['name']} ({col['type']})" for col in columns]
            schema_text += f"Table '{table}': {', '.join(col_names)}\n"

        return schema_text if schema_text else "No tables found in database."
    except Exception as e:
        return f"Error extracting schema: {e}"


def is_safe_sql(query: str) -> tuple[bool, str]:
    """Validates that a query is a safe, read-only operation."""
    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
    clean_query = query.strip().upper()

    if not (clean_query.startswith("SELECT") or clean_query.startswith("WITH")):
        return False, "Only read-only SELECT queries are allowed."

    for kw in forbidden:
        if kw in clean_query:
            return False, f"Operation '{kw}' is restricted."

    return True, "Safe"


def save_connection(db_type, name, conn_url):
    """Saves connection settings to session history."""
    if not any(
        c["url"] == conn_url for c in st.session_state["saved_connections"]
    ):
        st.session_state["saved_connections"].append(
            {"type": db_type, "name": name, "url": conn_url}
        )


def disconnect_db():
    """Disconnects the active database engine."""
    if st.session_state.get("db_engine"):
        st.session_state["db_engine"].dispose()
    st.session_state["db_engine"] = None
    st.session_state["db_type"] = "None"


def render_data_visualization(df, key_prefix):
    """Renders charts automatically for numeric data."""
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    all_cols = df.columns.tolist()

    if len(num_cols) >= 1 and len(all_cols) >= 2:
        with st.expander("Data Visualization", expanded=False):
            col_type, col_x, col_y = st.columns(3)

            with col_type:
                chart_type = st.selectbox(
                    "Chart Type",
                    ["Bar Chart", "Line Chart", "Scatter Plot"],
                    key=f"{key_prefix}_chart_type",
                )
            with col_x:
                default_x = [c for c in all_cols if c not in num_cols]
                x_axis = st.selectbox(
                    "X-Axis",
                    options=all_cols,
                    index=all_cols.index(default_x[0]) if default_x else 0,
                    key=f"{key_prefix}_x_axis",
                )
            with col_y:
                y_axis = st.selectbox(
                    "Y-Axis",
                    options=num_cols,
                    index=0,
                    key=f"{key_prefix}_y_axis",
                )

            if chart_type == "Bar Chart":
                st.bar_chart(data=df, x=x_axis, y=y_axis)
            elif chart_type == "Line Chart":
                st.line_chart(data=df, x=x_axis, y=y_axis)
            elif chart_type == "Scatter Plot":
                st.scatter_chart(data=df, x=x_axis, y=y_axis)


def generate_dataframe_summary(df: pd.DataFrame, original_query: str) -> str:
    """Generates a plain-text summary of execution results using OpenRouter."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "API key missing. Cannot generate summary."

    sample_data = df.head(10).to_string(index=False)
    prompt = (
        f"User Query: '{original_query}'\n\n"
        f"Query Output:\n{sample_data}\n\n"
        "Provide a concise, 2-sentence summary highlighting key takeaways or statistics."
    )

    try:
        with OpenRouter(api_key=api_key) as client:
            response = client.chat.send(
                model="dots-studio/dots-3-note-preview:free",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional data analyst assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            if response and response.choices:
                return response.choices[0].message.content.strip()
            return "Unable to generate summary."
    except Exception as e:
        return f"Summary error: {e}"


# ---------------------------------------------------------
# SIDEBAR NAVIGATION
# ---------------------------------------------------------
st.sidebar.title("Navigation")

if st.session_state.get("pending_redirect"):
    st.session_state["current_page"] = st.session_state["pending_redirect"]
    st.session_state["pending_redirect"] = None

pages = ["Home", "Connection", "Schema Viewer"]
default_idx = pages.index(st.session_state["current_page"])

page = st.sidebar.radio("Select View:", pages, index=default_idx)
st.session_state["current_page"] = page

st.sidebar.markdown("---")
if st.sidebar.button("Clear Conversation", use_container_width=True):
    st.session_state["messages"] = []
    st.rerun()


# ---------------------------------------------------------
# PAGE: HOME (CHAT INTERFACE)
# ---------------------------------------------------------
if page == "Home":
    st.title("SQL AI Assistant")

    if not st.session_state.get("db_engine"):
        st.info(
            "No active database connection. Please configure a connection to proceed."
        )
        if st.button("Go to Connection Settings", type="primary"):
            st.session_state["pending_redirect"] = "Connection"
            st.session_state["current_page"] = "Connection"
            if "nav_radio" in st.session_state:
                del st.session_state["nav_radio"]
            st.rerun()
    else:
        # Render historical chat context
        for idx, message in enumerate(st.session_state["messages"]):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

                if "sql" in message:
                    sql_code = message["sql"]
                    st.code(sql_code, language="sql")

                    # Execution Controls
                    col_run, col_space = st.columns([1, 4])
                    with col_run:
                        if st.button("Run Query", key=f"run_btn_{idx}"):
                            is_safe, err_msg = is_safe_sql(sql_code)
                            if not is_safe:
                                st.error(err_msg)
                            else:
                                try:
                                    engine = st.session_state["db_engine"]
                                    df_res = pd.read_sql_query(
                                        sql_code, con=engine
                                    )
                                    st.session_state["messages"][idx][
                                        "df"
                                    ] = df_res
                                    st.rerun()
                                except Exception as db_err:
                                    st.error(f"Database Error: {db_err}")

                    # Render Query Results
                    if "df" in message:
                        st.markdown("**Results:**")
                        st.dataframe(message["df"], use_container_width=True)

                        render_data_visualization(
                            message["df"], key_prefix=f"vis_{idx}"
                        )

                        btn_col1, btn_col2, _ = st.columns([1, 1.5, 2.5])
                        with btn_col1:
                            csv_data = (
                                message["df"]
                                .to_csv(index=False)
                                .encode("utf-8")
                            )
                            st.download_button(
                                label="Download CSV",
                                data=csv_data,
                                file_name="results.csv",
                                mime="text/csv",
                                key=f"dl_btn_{idx}",
                            )
                        with btn_col2:
                            if st.button(
                                "Summarize Results", key=f"sum_btn_{idx}"
                            ):
                                with st.spinner("Generating summary..."):
                                    summary_text = generate_dataframe_summary(
                                        message["df"], message.get("sql", "")
                                    )
                                    st.session_state["messages"][idx][
                                        "summary"
                                    ] = summary_text
                                    st.rerun()

                        if "summary" in message:
                            st.info(f"**Insight:** {message['summary']}")

        # Chat Input Bar
        if user_prompt := st.chat_input("Ask a question about your data..."):
            api_key = os.getenv("OPENROUTER_API_KEY")

            if not api_key:
                st.error("API key not found in `.env` file.")
            else:
                st.session_state["messages"].append(
                    {"role": "user", "content": user_prompt}
                )

                engine = st.session_state.get("db_engine")
                schema_context = get_database_schema_context(engine)

                system_instruction = (
                    f"You are an expert {st.session_state.get('db_type', 'SQL')} generator.\n\n"
                    f"DATABASE SCHEMA:\n{schema_context}\n\n"
                    "RULES:\n"
                    "1. Use ONLY table and column names explicitly defined in the schema.\n"
                    "2. Return ONLY executable SQL query on a single line without markdown block or backticks."
                )

                try:
                    with st.spinner("Generating SQL..."):
                        with OpenRouter(api_key=api_key) as client:
                            response = client.chat.send(
                                model="dots-studio/dots-3-note-preview:free",
                                messages=[
                                    {
                                        "role": "system",
                                        "content": system_instruction,
                                    },
                                    {"role": "user", "content": user_prompt},
                                ],
                            )

                            if response and response.choices:
                                raw_sql = (
                                    response.choices[0]
                                    .message.content.strip()
                                )
                                clean_sql = (
                                    raw_sql.replace("```sql", "")
                                    .replace("```", "")
                                    .strip()
                                )

                                st.session_state["messages"].append(
                                    {
                                        "role": "assistant",
                                        "content": "Generated SQL Query:",
                                        "sql": clean_sql,
                                    }
                                )
                                st.rerun()
                            else:
                                st.error("No response from model.")

                except Exception as e:
                    st.error(f"OpenRouter Error: {e}")


# ---------------------------------------------------------
# PAGE: CONNECTION SETTINGS
# ---------------------------------------------------------
elif page == "Connection":
    st.title("Database Connection")

    # Connect Form
    st.subheader("Configure New Connection")
    db_choice = st.selectbox(
        "Database Engine",
        ["SQLite (Local File)", "PostgreSQL", "MySQL"],
    )

    if db_choice == "SQLite (Local File)":
        sqlite_file = st.text_input(
            "File Path (Use `:memory:` for temp database)", value=":memory:"
        )

        if st.button("Connect", type="primary"):
            try:
                conn_url = f"sqlite:///{sqlite_file}"
                engine = create_engine(conn_url)
                with engine.connect():
                    pass

                st.session_state["db_engine"] = engine
                st.session_state["db_type"] = "SQLite"
                save_connection("SQLite", sqlite_file, conn_url)
                st.success("Connected to SQLite database.")
                st.rerun()
            except Exception as e:
                st.error(f"Connection failed: {e}")

    else:
        col1, col2 = st.columns(2)
        with col1:
            host = st.text_input("Host", value="localhost")
            port = st.text_input(
                "Port", value="5432" if db_choice == "PostgreSQL" else "3306"
            )
            database = st.text_input("Database Name", value="sql_test")
        with col2:
            username = st.text_input("Username", value="root")
            password = st.text_input("Password", type="password")

        if st.button(f"Connect to {db_choice}", type="primary"):
            try:
                if db_choice == "PostgreSQL":
                    conn_url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
                elif db_choice == "MySQL":
                    conn_url = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"

                engine = create_engine(conn_url)
                with engine.connect():
                    pass

                st.session_state["db_engine"] = engine
                st.session_state["db_type"] = db_choice
                save_connection(
                    db_choice, f"{database} ({host}:{port})", conn_url
                )
                st.success(f"Connected to {db_choice}.")
                st.rerun()
            except Exception as e:
                st.error(f"Connection failed: {e}")

    st.markdown("---")

    # Status & Recent Connections
    st.subheader("Status & History")
    if st.session_state.get("db_engine"):
        st.success(f"Active: **{st.session_state.get('db_type')}** engine")
        if st.button("Disconnect"):
            disconnect_db()
            st.rerun()
    else:
        st.info("Status: Disconnected")

    st.write("**Saved Connections**")
    if not st.session_state["saved_connections"]:
        st.caption("No saved connection profiles.")
    else:
        for idx, conn in enumerate(st.session_state["saved_connections"]):
            c_col1, c_col2 = st.columns([3, 1])
            with c_col1:
                st.write(f"**{conn['type']}**: `{conn['name']}`")
            with c_col2:
                if st.button("Reconnect", key=f"reconn_{idx}"):
                    try:
                        engine = create_engine(conn["url"])
                        with engine.connect():
                            pass
                        st.session_state["db_engine"] = engine
                        st.session_state["db_type"] = conn["type"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Reconnection failed: {e}")


# ---------------------------------------------------------
# PAGE: SCHEMA VIEWER
# ---------------------------------------------------------
elif page == "Schema Viewer":
    st.title("Schema Inspector")

    if not st.session_state.get("db_engine"):
        st.info("Connect to a database to inspect tables and schemas.")
    else:
        try:
            engine = st.session_state["db_engine"]
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            if not tables:
                st.caption("No tables found in database.")
            else:
                selected_table = st.selectbox("Select Table:", tables)

                if selected_table:
                    columns = inspector.get_columns(selected_table)
                    st.markdown(f"**Structure: `{selected_table}`**")

                    col_info = [
                        {"Column": col["name"], "Type": str(col["type"])}
                        for col in columns
                    ]
                    st.table(col_info)

                    st.markdown(f"**Preview: `{selected_table}`**")
                    df_preview = pd.read_sql_query(
                        f"SELECT * FROM {selected_table} LIMIT 10", con=engine
                    )
                    st.dataframe(df_preview, use_container_width=True)

        except Exception as e:
            st.error(f"Error inspecting schema: {e}")