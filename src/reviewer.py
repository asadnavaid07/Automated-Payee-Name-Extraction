import os
import pandas as pd
import streamlit as st
import sys
import argparse


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    
    # Remove duplicate columns first
    df = df.loc[:, ~df.columns.duplicated()]
    
    # Ensure all required columns exist with proper names
    required_columns = {
        'Check Number': 'check_number',
        'payee_name': 'payee_name', 
        'amount': 'amount',
        'date': 'date',
        'bank': 'bank',
        'img_front_path': 'img_front_path',
        'img_back_path': 'img_back_path',
        'confidence': 'confidence',
        'source': 'source'
    }
    
    for display_name, col_name in required_columns.items():
        if col_name not in df.columns and display_name not in df.columns:
            df[col_name] = ''
        elif display_name in df.columns and col_name not in df.columns:
            # Rename display name to standard name
            df[col_name] = df[display_name]
            if col_name != display_name:
                df = df.drop(columns=[display_name])

    # Fill NaN values with empty strings for string columns
    string_columns = ['check_number', 'payee_name', 'amount', 'date', 'bank', 'img_front_path', 'img_back_path', 'source']
    for col in string_columns:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)

    try:
        df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce').fillna(0.0)
    except Exception:
        df['confidence'] = 0.0
    return df


def main() -> None:
    st.set_page_config(page_title="Check Payee Reviewer", layout="wide")
    st.title("Check Payee Reviewer")

    # Parse command line arguments for CSV path
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv-path', help='Path to the final CSV file')
    args = parser.parse_args()
    
    st.sidebar.header("Data")
    default_csv_path = args.csv_path if args.csv_path else ""
    parsed_csv_path = st.sidebar.text_input(
        "Final CSV path",
        value=default_csv_path,
        placeholder="e.g. C:/path/to/statement_final.csv",
    )

    uploaded = st.sidebar.file_uploader("Or upload final CSV", type=["csv"])

    df = None
    if uploaded is not None:
        df = load_csv(uploaded)
    elif parsed_csv_path and os.path.exists(parsed_csv_path):
        df = load_csv(parsed_csv_path)

    if df is None:
        st.info("Provide a final CSV path or upload a CSV to begin.")
        return

    st.sidebar.header("Filters")
    min_conf = st.sidebar.slider("Max confidence threshold", 0.0, 1.0, 0.85, 0.01)
    show_only_low_conf = st.sidebar.checkbox("Show only low-confidence rows", value=True)
    account_filter = st.sidebar.text_input("Bank contains", value="")

    view_df = df.copy()
    if show_only_low_conf:
        view_df = view_df[view_df['confidence'] < min_conf]
    if account_filter:
        view_df = view_df[view_df['bank'].astype(str).str.contains(account_filter, case=False, na=False)]

    st.subheader(f"Review {len(view_df)} checks")
    
    # Simple help text
    if len(view_df) > 0:
        st.info("💡 Review each check below. Compare the extracted payee name with the check image and adjust if needed.")

    if len(view_df) == 0:
        st.success("No rows to review at current threshold.")
        return

    edited_rows = 0

    for idx, row in view_df.iterrows():
        check_num = row.get('check_number', '') or row.get('Check Number', '')
        confidence = row.get('confidence', 0)
        
        # Simple expander title
        if confidence < 0.5:
            expander_title = f"Check {check_num} (Needs Review - {confidence:.1%})"
        else:
            expander_title = f"Check {check_num} ({confidence:.1%})"
        
        with st.expander(expander_title, expanded=confidence < 0.5):
            # Images section - clean and simple
            front_path = row.get('img_front_path', '')
            back_path = row.get('img_back_path', '')
            
            # Ensure paths are strings and not NaN/float
            front_path = str(front_path) if pd.notna(front_path) and front_path != '' else ''
            back_path = str(back_path) if pd.notna(back_path) and back_path != '' else ''
            
            # Display images side by side
            if (front_path and os.path.exists(front_path)) or (back_path and os.path.exists(back_path)):
                image_cols = st.columns(2)
                
                with image_cols[0]:
                    if front_path and os.path.exists(front_path):
                        st.image(front_path, caption="Front", use_column_width=True)
                    else:
                        st.text("Front image not available")
                
                with image_cols[1]:
                    if back_path and os.path.exists(back_path):
                        st.image(back_path, caption="Back", use_column_width=True)
                    else:
                        st.text("Back image not available")
            else:
                st.warning("No check images available")
            
            # Simple form
            current_payee = str(row.get('payee_name', ''))
            new_payee = st.text_input("Payee Name", value=current_payee, key=f"payee_{idx}")
            
            col1, col2 = st.columns(2)
            with col1:
                new_conf = st.slider("Confidence", 0.0, 1.0, float(confidence), 0.01, key=f"conf_{idx}")
            with col2:
                new_source = st.selectbox("Source", options=["ocr", "api", "manual"], index=2, key=f"src_{idx}")

            if st.button("Save", key=f"save_{idx}"):
                df.at[idx, 'payee_name'] = new_payee
                df.at[idx, 'confidence'] = new_conf
                df.at[idx, 'source'] = new_source
                edited_rows += 1
                st.success("Saved!")
                st.rerun()

    st.markdown("---")
    
    # Simple download section
    col1, col2 = st.columns(2)
    
    with col1:
        st.download_button(
            label="Download CSV",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name="statement_final.csv",
            mime="text/csv"
        )
    
    with col2:
        if parsed_csv_path and os.path.exists(parsed_csv_path):
            if st.button("Save to Original File"):
                try:
                    df.to_csv(parsed_csv_path, index=False)
                    st.success("Saved!")
                except Exception as e:
                    st.error(f"Error: {str(e)}")


if __name__ == "__main__":
    main()


