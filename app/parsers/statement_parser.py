import pandas as pd
from typing import List, Set, Dict, Any, Tuple
from datetime import datetime
import google.generativeai as genai
import json
import os
from dotenv import load_dotenv
from ..models import CheckTransaction


load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

DATE_FORMATS = [
    "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d",
    "%b %d, %Y", "%d %b %Y", "%m/%d/%y", "%d/%m/%y"
]

class StatementParser:
    def __init__(self):
        pass

    def _prepare_column_analysis(self, df: pd.DataFrame, max_sample_rows: int = 3) -> List[Dict[str, Any]]:

        column_info = []
        
        for col_idx, col_name in enumerate(df.columns):

            sample_values = []
            for row_idx in range(min(max_sample_rows, len(df))):
                value = df.iloc[row_idx, col_idx]  
                sample_values.append(str(value) if pd.notna(value) else "")
            
            column_info.append({
                "index": col_idx,
                "name": col_name,
                "samples": sample_values
            })
        
        return column_info

    def _map_columns_with_llm(self, column_info: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Map columns to fields, returning column INDEX (not name) to handle duplicates.
        """
        if not column_info:
            return {"check_number": None, "date": None, "amount": None}

        # Create a readable representation of columns with their sample data
        columns_desc = []
        for col in column_info:
            samples_str = ", ".join([f"'{v}'" for v in col["samples"] if v])
            columns_desc.append(f"Column {col['index']} (name: '{col['name']}'): sample values = [{samples_str}]")
        
        prompt = f"""
Analyze these CSV columns from a bank statement:

{chr(10).join(columns_desc)}

Your task: Identify which column INDEX corresponds to each field:
- check_number: Check/transaction/reference numbers (alphanumeric identifiers)
- date: Transaction dates (any date format)
- amount: Transaction amounts (positive monetary values representing actual payments/debits)

CRITICAL RULES:
1. Return the column INDEX (0, 1, 2, etc.), NOT the column name
2. When multiple columns have the same name, analyze the SAMPLE VALUES to choose the correct one
3. For amount: Choose the column with meaningful positive amounts (not zeros or empty values)
4. Only map if you're confident based on the sample values
5. Return null for any field if no suitable column found

Return ONLY valid JSON (no markdown):
{{"check_number": <index or null>, "date": <index or null>, "amount": <index or null>}}

Example: {{"check_number": 0, "date": 1, "amount": 3}}
"""
        
        try:
            model = genai.GenerativeModel('gemini-2.0-flash-exp')
            response = model.generate_content(prompt)
            mapping_json = response.text.strip()
            
            if mapping_json.startswith("```"):
                lines = mapping_json.split('\n')
                mapping_json = '\n'.join(lines[1:-1]) if len(lines) > 2 else mapping_json
                mapping_json = mapping_json.replace("```json", "").replace("```", "").strip()
            
            mapping = json.loads(mapping_json)
            
            max_idx = len(column_info) - 1
            for key, value in mapping.items():
                if value is not None and (not isinstance(value, int) or value < 0 or value > max_idx):
                    print(f"Warning: Invalid index {value} for {key}, setting to None")
                    mapping[key] = None
            
            print(f"LLM mapped: {mapping}")
            return mapping
            
        except Exception as e:
            print(f"LLM error: {e}. Using fallback.")
            return self._fallback_mapping(column_info)

    def _fallback_mapping(self, column_info: List[Dict[str, Any]]) -> Dict[str, int]:
        mapping = {"check_number": None, "date": None, "amount": None}
        
        check_scores = []
        date_scores = []
        amount_scores = []
        
        for col in column_info:
            col_idx = col["index"]
            col_name = col["name"].lower()
            samples = col["samples"]
            
            check_score = 0
            if any(kw in col_name for kw in ["check", "chk", "slip", "trans", "reference", "ref"]):
                check_score += 50
            if any(self._looks_like_check_number(s) for s in samples):
                check_score += 30
            check_scores.append((col_idx, check_score))
            
            date_score = 0
            if any(kw in col_name for kw in ["date", "post", "trans"]):
                date_score += 50
            if any(self._looks_like_date(s) for s in samples):
                date_score += 40
            date_scores.append((col_idx, date_score))
            
            amount_score = 0
            if any(kw in col_name for kw in ["amount", "debit", "payment", "withdrawal"]):
                amount_score += 30
            
            positive_count = 0
            zero_count = 0
            total = 0.0
            valid_count = 0
            
            for sample in samples:
                clean = sample.replace(',', '').replace('$', '').strip()
                if clean and clean.lower() not in ['nan', '', 'none']:
                    try:
                        val = float(clean)
                        valid_count += 1
                        if val > 0:
                            positive_count += 1
                            total += val
                        elif val == 0:
                            zero_count += 1
                    except ValueError:
                        pass
            
            if valid_count > 0:
                amount_score += valid_count * 10
                amount_score += (positive_count / valid_count) * 40
                amount_score -= (zero_count / valid_count) * 20
                
                if positive_count > 0:
                    avg = total / positive_count
                    if avg > 1:
                        amount_score += 15
                    if avg > 50:
                        amount_score += 10
            
            amount_scores.append((col_idx, amount_score))
        
        check_scores.sort(key=lambda x: x[1], reverse=True)
        if check_scores[0][1] > 30:
            mapping["check_number"] = check_scores[0][0]
        
        date_scores.sort(key=lambda x: x[1], reverse=True)
        if date_scores[0][1] > 40:
            mapping["date"] = date_scores[0][0]
        
        amount_scores.sort(key=lambda x: x[1], reverse=True)
        if amount_scores[0][1] > 20:
            mapping["amount"] = amount_scores[0][0]
        
        print(f"Fallback mapped: {mapping}")
        return mapping

    def _looks_like_check_number(self, value: str) -> bool:
        if not value or len(value) < 2:
            return False
        return any(c.isalnum() for c in value) and value.lower() not in ['nan', 'none', 'true', 'false']

    def _looks_like_date(self, value: str) -> bool:
        if not value or len(value) < 6:
            return False
        # Try to parse as date
        for fmt in DATE_FORMATS:
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
        return False

    def parse_csv_section(self, df: pd.DataFrame) -> List[CheckTransaction]:
        checks = []
        
        if df.empty:
            return checks
        
        column_info = self._prepare_column_analysis(df)
        col_map = self._map_columns_with_llm(column_info)
        
        if col_map.get("check_number") is None:
            print(f"No check_number column identified")
            return checks
        
        check_col_idx = col_map["check_number"]
        date_col_idx = col_map.get("date")
        amount_col_idx = col_map.get("amount")
        
        print(f"Using columns: check={check_col_idx}, date={date_col_idx}, amount={amount_col_idx}")
        
        for row_idx in range(len(df)):
            try:
                check_number = str(df.iloc[row_idx, check_col_idx]).strip()
                if not check_number or check_number.lower() in ['nan', 'none', '', 'true', 'false']:
                    continue
                
                date_obj = None
                if date_col_idx is not None:
                    date_str = str(df.iloc[row_idx, date_col_idx]).strip()
                    if date_str and date_str.lower() not in ['nan', 'none', '']:
                        for fmt in DATE_FORMATS:
                            try:
                                date_obj = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                
                amount = None
                if amount_col_idx is not None:
                    amount_str = str(df.iloc[row_idx, amount_col_idx]).replace(',', '').replace('$', '').strip()
                    if amount_str and amount_str.lower() not in ['nan', 'none', '']:
                        try:
                            amount = float(amount_str)
                        except ValueError:
                            pass
                
                checks.append(CheckTransaction(
                    check_number=check_number,
                    date=date_obj,
                    amount=amount
                ))
                
            except Exception as e:
                print(f"Error processing row {row_idx}: {e}")
                continue
        
        return checks

    def parse_statement(self, file_path: str) -> List[CheckTransaction]:
        if not file_path.endswith('.csv'):
            raise ValueError("Only CSV files are supported")
        
        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False, header=None)
            if df.empty:
                return []
        except Exception as e:
            raise ValueError(f"Error reading CSV: {str(e)}")
        
        sections = []
        current_section = []
        
        for idx, row in df.iterrows():
            if row.isna().all() or all(str(v).strip() == '' for v in row):
                if current_section and len(current_section) > 1:
                    section_df = pd.DataFrame(current_section[1:], columns=current_section[0])
                    sections.append(section_df)
                current_section = []
            else:
                current_section.append(row.tolist())
        
        if current_section and len(current_section) > 1:
            section_df = pd.DataFrame(current_section[1:], columns=current_section[0])
            sections.append(section_df)
        
        if not sections:
            return []

        all_checks: List[CheckTransaction] = []
        seen_check_numbers: Set[str] = set()
        
        for i, section_df in enumerate(sections, 1):
            if section_df.empty:
                continue
            
            print(f"\nProcessing section {i}")
            section_checks = self.parse_csv_section(section_df)
            
            for check in section_checks:
                if check.check_number not in seen_check_numbers:
                    seen_check_numbers.add(check.check_number)
                    all_checks.append(check)
        
        all_checks.sort(key=lambda x: x.check_number)
        
        if all_checks:
            export_df = pd.DataFrame([{
                "Check Number": chk.check_number,
                "Date": chk.date.strftime("%Y-%m-%d") if chk.date else "",
                "Amount": chk.amount if chk.amount is not None else ""
            } for chk in all_checks])
            
            export_path = file_path.replace('.csv', '_parsed.csv')
            export_df.to_csv(export_path, index=False)
            print(f"\nExported {len(all_checks)} checks to {export_path}")
        
        return all_checks

parser = StatementParser()

def parse_statement(file_path: str) -> List[CheckTransaction]:
    return parser.parse_statement(file_path)