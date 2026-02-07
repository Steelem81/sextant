import snowflake.connector 
from anthropic import Anthropic
import pandas as pd
import gradio as gr
from config import config
import plotly.express as px
import plotly.graph_objects as go




class SnowflakeService:
    def __init__(self):
        self.anthropic_client = Anthropic(api_key=config.anthropic_api_key)
        self.snowflake_config = {
            'user': config.snowflake_user,
            'password': config.snowflake_password,
            'account': config.snowflake_account,
            'warehouse': config.snowflake_warehouse,
            'database': config.snowflake_database,
            'schema': config.snowflake_schema
        }

    def connect_snowflake(self):
        print("connecting to snowflake")
        try:
            conn = snowflake.connector.connect(
                user= self.snowflake_config['user'],
                password=config.snowflake_password,
                account=config.snowflake_account,
                warehouse=config.snowflake_warehouse,
                database=config.snowflake_database,
                schema=config.snowflake_schema
                )
            print("Connectedtion established")
            return conn
        except Exception as e:
            raise Exception(f"Failed to connect to snowflake: {str(e)}")
    
    def get_table_schema(self, conn):
        print("Establishing Schema")
        try:
            cursor = conn.cursor()

            cursor.execute(f"USE DATABASE {self.snowflake_config['database']}")
            cursor.execute(f"USE SCHEMA {self.snowflake_config['schema']}")
            
            print("executing Schema sql")
            cursor.execute(f"""
                           SELECT
                           *
                           FROM information_schema.tables
                           WHERE UPPER(table_schema) = '{self.snowflake_config['schema']}'
                           """)

            results = cursor.fetchall()

            tables = [row[2] for row in results]
            print(f"Tables included: {tables}")

            schema_info = []
            for table in tables:
                cursor.execute(f"""
                               SELECT column_name, data_type
                               FROM information_schema.columns
                               WHERE UPPER(table_name) = '{table}'
                               AND UPPER(table_schema) ='{self.snowflake_config['schema']}'
                               """)
                columns = cursor.fetchall()
                schema_info.append(f"Table: {table}")
                for col_name, col_type in columns:
                    schema_info.append(f" - {col_name} ({col_type})")

            cursor.close()
            print("Schema fetched")
            return "\n".join(schema_info)
        except Exception as e:
            return f"Error fetching schema: {str(e)}"

    def generate_sql(self, user_query, schema_info):
        
        system_prompt = f"""You are an expert DQL analyst working with Snowflake databases. 
        Your job is to convert natural language questions into accurate SQL queries.
        Here is the database schema you are working with: {schema_info}
        Guidelines:
        1. Generate only the SQL query without markdown formatting, do not provide explanations.
        2. Use proper Snowflake SQL syntax
        3. Include appropriate aggregations and date functions
        4. For time-based queries, use DATE_TRUNC or similar functions
        5. Always include proper WHERE clauses for date filtering when relevant
        6. Use CTEs for complex queries
        7. Return results that can be easily visualized
        8. Always truncate a timestamp or date column to a date when used in a function, DATE_TRUNC, or WHERE clause
        9. Never provide an individual user's name, email, id, or date of birth

        Return only the SQL query without markdown."""

        try:
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens = 1000,
                system = system_prompt,
                messages=[
                    {"role": "user", "content": f"\nUser question: {user_query}"}
                ]
            )

            sql_query = response.content[0].text.strip()
            print(sql_query)
            return sql_query
        except Exception as e:
            raise Exception(f"Error generating SQL: {str(e)}")
    
    def retrieve_results(self, conn, sql_query):
        print("Retrieving Results")
        try:
            cursor = conn.cursor()
            cursor.execute(sql_query)
            results = cursor.fetchall()
            
            columns = [desc[0] for desc in cursor.description]
            print("Results to DF")
            df = pd.DataFrame(results, columns=columns)

            cursor.close()

            

            return df
        
        except Exception as e:
            print(f"Error running SQL query: {str(e)}")

    def graph_data(self, df, query):
        print("graphing data")
        print(f"DF is empty: {df.empty}")
        print(df.columns)
        if df.empty:
            fig = go.Figure()
            fig.add_annotation(text="No data available",
                                xref="paper",
                                yref="paper",
                                x=0.5,
                                y=0.5,
                                showarrow=False)
            return fig
        
        cols = df.columns.tolist()
        query_lower = query.lower()

        
        date_cols = [col for col in cols if any(term in col.lower() for term in ['date', 'time', 'month', 'week', 'day', 'year', 'quarter'])]
        print(f"Num Date Columns: {len(date_cols)}")
        if date_cols and len(cols) >= 2:
            x_col = date_cols[0]
            y_cols = [col for col in cols if col != x_col]

            fig = px.line(df, 
                          x=x_col,
                          y=y_cols[0] if len(y_cols) == 1 else y_cols,
                          labels={x_col: x_col.replace('_', ' ').title()})
            
        elif 'trend' in query_lower or 'over time' in query_lower:
            print("Trending visual")
            fig = px.line(df,
                          x=cols[0],
                          y=cols[1:],
                          title="Trend Analysis")
            
        elif 'distribution' in query_lower or 'breakdown' in query_lower:
            print("Distribution visual")
            if len(df) <= 10:
                fig = px.pie(df, names=cols[0], values=cols[1], title="Distribution")
            else:
                fig = px.bar(df, x=cols[0], y=cols[1], title="Distribution")

        else:
            print("Default Visual")
            fig = px.bar(df,
                         x=cols[0], 
                         y=cols[1:] if len(cols) >2 else cols[1],
                         title= "Metrics Visualization")
        
        fig.update_layout(
            template="plotly_white",
            hovermode='x unified',
            showlegend=True,
            height=500
        )

        return fig

    def process_query(self, user_query):

        try:
            conn = self.connect_snowflake()
            schema = self.get_table_schema(conn)
            sql_query = self.generate_sql(user_query, schema_info=schema)
            results_df = self.retrieve_results(conn, sql_query)
            fig = self.graph_data(results_df, user_query)
  

            return (
                results_df,
                fig,
                sql_query
            )
        
        except Exception as e:
            print(f"Failed to process query: {str(e)}")
def create_gradio_interface():
    app = SnowflakeService()

    with gr.Blocks() as interface:
        gr.Markdown("# AI-Powered Dashboard")
        gr.Markdown("Ask questions about subscription data")

        with gr.Row():
            with gr.Column(scale=3):
                query_input = gr.Textbox(
                    label="Ask a question about subscription metrics",
                    placeholder= "e.g., How many new subscriptions did we see in the last quarter",
                    lines=2
                )
    
        submit_btn = gr.Button("Submit")

        with gr.Tabs():
            with gr.Tab("Data Table"):
                table_output = gr.Dataframe(label="Query Results")
            with gr.Tab("Visualization"):
                plot_output = gr.Plot(label="Metrics Visualization")
            with gr.Tab("SQL Query"):
                sql_output = gr.Code(label="Generated SQL", language="sql")
        
        submit_btn.click(
            fn=app.process_query,
            inputs = [query_input],
            outputs=[table_output, plot_output, sql_output]
        )

    return interface
        
if __name__ == "__main__":
    config = config

    try:
       interface = create_gradio_interface()
       interface.launch(
           share=config.gradio_share,
           server_name=config.gradio_server_name,
           server_port = config.gradio_server_port
       )


    except Exception as e:
        print(f"Test failed{e}")
            
