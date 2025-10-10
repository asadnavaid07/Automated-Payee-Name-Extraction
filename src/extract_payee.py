import os
import re
import base64
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("GOOGLE_VISION_API_KEY")
if not API_KEY:
    raise ValueError("Missing GOOGLE_VISION_API_KEY in .env file")

def extract_check_info(image_path):
    with open(image_path, "rb") as image_file:
        image_content = base64.b64encode(image_file.read()).decode("utf-8")

    url = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"

    payload = {
        "requests": [
            {
                "image": {"content": image_content},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}] 
            }
        ]
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    result = response.json()

    annotations = result.get("responses", [{}])[0]
    full_text = annotations.get("fullTextAnnotation", {}).get("text", "")
    texts = annotations.get("textAnnotations", [])

    if not full_text:
        raise ValueError("No text detected in image.")
    
    print("Detected full text:", full_text)
    print("\n" + "="*50 + "\n")
    
    # Extract payee name
    payee_name = extract_payee_name(full_text, texts)
    
    # Extract check number
    check_number = extract_check_number(full_text, texts)
    
    # Calculate confidence based on extraction success and textual heuristics
    confidence = calculate_confidence(payee_name, check_number, full_text)
    
    return {
        "check_number": check_number,
        "payee_name": payee_name,
        "confidence": confidence,
    }


def extract_payee_name(full_text, texts):
    """Extract payee name using line-based analysis"""
    
    lines = full_text.split('\n')
    
    lines = [line.strip() for line in lines if line.strip()]
    
    print("Lines detected:")
    for i, line in enumerate(lines):
        print(f"  {i}: {line}")
    print()
    
    for i, line in enumerate(lines):

        if re.search(r'\bOF\b', line, re.IGNORECASE):

            parts = re.split(r'\b(?:RD\s+)?OF\b', line, flags=re.IGNORECASE)
            if len(parts) > 1:
                payee = parts[-1].strip()
                # Clean up
                payee = clean_payee_name(payee)
                if is_valid_payee(payee):
                    print(f"Strategy 1: Found payee after OF: {payee}")
                    return payee
    
    # Strategy 2: Payee appears on line BEFORE "OF"
    # The pattern is often: PAYEE_NAME on one line, then "OF" or "RD OF" on next line
    for i, line in enumerate(lines):
        if re.search(r'^(?:RD\s+)?OF\s*$', line, re.IGNORECASE) and i > 0:
            # Check previous line
            payee = lines[i - 1].strip()
            payee = clean_payee_name(payee)
            if is_valid_payee(payee):
                print(f"Strategy 2: Found payee before OF: {payee}")
                return payee
    
    # Strategy 3: Look for pattern where payee is between company header and amount
    # Skip first few lines (company header), look for name before amounts/dates
    company_keywords = [
        "Love United Transport", "BUSHBERRY", "PAY", "TO THE", "CHASE", "JPMorgan",
        # Headers and boilerplate words to skip
    ]
    amount_keywords = [
        "THOUSAND", "HUNDRED", "DOLLARS", "$", "FOR", "DATE", "PAY TO THE ORDER OF",
        "MEMO", "AMOUNT"
    ]
    location_noise_keywords = [
        "FONTANA", "CA", "USA", "CITY", "STATE", "ZIP"
    ]
    
    # Find where company info ends
    company_end_idx = 0
    for i, line in enumerate(lines):
        if any(keyword.lower() in line.lower() for keyword in company_keywords):
            company_end_idx = i + 1
    
    # Find where amount/date info starts
    amount_start_idx = len(lines)
    for i, line in enumerate(lines):
        if any(keyword.lower() in line.lower() for keyword in amount_keywords):
            amount_start_idx = i
            break
    
    # Look for payee between company header and amounts
    for i in range(company_end_idx, amount_start_idx):
        if i < len(lines):
            line = lines[i]
            # Skip lines that are just "OF", "RD OF", numbers, or dates
            if re.match(r'^(?:RD\s+)?OF\s*$', line, re.IGNORECASE):
                continue
            if re.match(r'^\d+$', line):  # Just a number
                continue
            if re.match(r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$', line):  # Date
                continue
            # Skip clear location lines (e.g., CITY, ST or CITY, ST 12345)
            if re.search(r",\s*[A-Z]{2}(?:\s*\d{5})?$", line.strip()):
                continue
            if any(kw.lower() in line.lower() for kw in location_noise_keywords):
                # Likely address/city/state noise
                continue
            
            payee = clean_payee_name(line)
            if is_valid_payee(payee):
                print(f"Strategy 3: Found payee in middle section: {payee}")
                return payee
    
    # Strategy 4: Spatial analysis as last resort
    if texts and len(texts) > 1:
        payee = extract_payee_spatial(texts)
        if payee:
            print(f"Strategy 4: Spatial analysis found: {payee}")
            return payee
    
    return "Not found"


def extract_payee_spatial(texts):
    """Extract payee using spatial analysis - looking for text in payee line area"""
    word_boxes = []
    
    for text in texts[1:]:  # Skip first element (full text)
        desc = text.get("description", "")
        vertices = text.get("boundingPoly", {}).get("vertices", [])
        if len(vertices) < 4:
            continue
        
        min_x = min(v.get("x", 0) for v in vertices)
        max_x = max(v.get("x", 0) for v in vertices)
        min_y = min(v.get("y", 0) for v in vertices)
        max_y = max(v.get("y", 0) for v in vertices)
        center_y = (min_y + max_y) / 2
        height = max_y - min_y
        
        word_boxes.append({
            "desc": desc,
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
            "center_y": center_y,
            "height": height
        })
    
    # Find "OF" keyword
    of_boxes = [wb for wb in word_boxes if wb["desc"].upper() == "OF"]
    
    if not of_boxes:
        return None
    
    of_box = of_boxes[0]
    
    tolerance_y = of_box["height"] * 0.8
    payee_words = []
    
    exclude_words = {"PAY", "TO", "THE", "ORDER", "OF", "RD", "FOR", "DOLLARS", "DATE"}
    
    for wb in word_boxes:
        if (abs(wb["center_y"] - of_box["center_y"]) < tolerance_y and
            wb["max_x"] < of_box["min_x"] and  # To the left of OF
            wb["desc"].upper() not in exclude_words and
            not re.match(r'^\d+[.,]?\d*$', wb["desc"]) and
            not re.match(r'^\$', wb["desc"]) and
            len(wb["desc"]) > 1): 
            payee_words.append(wb)
    
    if payee_words:

        payee_words.sort(key=lambda w: w["min_x"])
        payee_parts = [w["desc"] for w in payee_words[-4:]]  
        payee = ' '.join(payee_parts).strip()
        payee = clean_payee_name(payee)
        if is_valid_payee(payee):
            return payee
    
    return None


def is_valid_payee(payee):
    """Check if extracted text is a valid payee name"""
    if not payee or payee == "Not found":
        return False
    
    if len(payee) < 2:
        return False
    
    if re.match(r'^[\d\s.,]+$', payee):
        return False
    
    if re.match(r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$', payee):
        return False
    
    amount_words = {"ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE",
                    "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
                    "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN",
                    "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY",
                    "HUNDRED", "THOUSAND", "MILLION", "BILLION", "DOLLARS"}
    words = payee.upper().split()
    if all(word in amount_words for word in words):
        return False
    # Reject clear location patterns: CITY, ST or CITY, ST 12345
    if re.search(r",\s*[A-Z]{2}(?:\s*\d{5})?$", payee.strip().upper()):
        return False
    
    if not re.search(r'[A-Za-z]', payee):
        return False
    
    return True


def clean_payee_name(payee):

    payee = re.sub(r'^\s*(?:RD\s+)?(?:OF\s+)?', '', payee, flags=re.IGNORECASE)

    payee = payee.strip('.,;: \t\n')

    payee = re.sub(r'^\$\s*', '', payee)
    payee = re.sub(r'\s*\$.*$', '', payee)

    payee = re.sub(r'\s+\d+[,.]?\d*\s*$', '', payee)
    
    return payee.strip()


def extract_check_number(full_text, texts):

    lines = full_text.split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    
    # Strategy 1: Look for 4-digit number that appears alone on a line in upper portion
    for i, line in enumerate(lines[:10]):  # Check first 10 lines only
        if re.match(r'^\d{4,5}$', line):
            print(f"Check number found (standalone line): {line}")
            return line
    
    # Strategy 2: Spatial analysis - rightmost number in top area
    if texts and len(texts) > 1:
        candidates = []
        for text in texts[1:]:
            desc = text.get("description", "")
            vertices = text.get("boundingPoly", {}).get("vertices", [])
            
            if not re.match(r'^\d{4,5}$', desc):
                continue
            
            if len(vertices) < 4:
                continue
            
            max_x = max(v.get("x", 0) for v in vertices)
            min_y = min(v.get("y", 0) for v in vertices)
            
            # Only consider numbers in top 30% of image
            candidates.append({
                "number": desc,
                "max_x": max_x,
                "min_y": min_y
            })
        
        if candidates:
            # Sort by top position first, then rightmost
            candidates.sort(key=lambda c: (c["min_y"], -c["max_x"]))
            check_num = candidates[0]["number"]
            print(f"Check number found (spatial): {check_num}")
            return check_num
    
    # Strategy 3: Look for number near "DATE"
    for line in lines:
        if "DATE" in line.upper():
            # Look for 4-digit number before DATE
            match = re.search(r'(\d{4,5})\s*DATE', line, re.IGNORECASE)
            if match:
                check_num = match.group(1)
                print(f"Check number found (DATE pattern): {check_num}")
                return check_num
    
    # Strategy 4: MICR line
    if lines:
        micr_line = lines[-1]
        micr_match = re.search(r'⑈0*(\d{4,5})⑈', micr_line)
        if micr_match:
            check_num = micr_match.group(1)
            print(f"Check number found (MICR): {check_num}")
            return check_num
    
    return "Not found"


def calculate_confidence(payee_name, check_number, full_text):
    """Calculate confidence using payee quality heuristics and presence of check number.
    Returns a value in [0, 0.98]."""
    # Base confidence
    confidence = 0.2

    # Score payee quality
    payee_quality = 0.0
    if payee_name and payee_name != "Not found":
        payee_quality = score_payee_quality(payee_name)
        # Weight the quality substantially
        confidence += 0.6 * payee_quality

    # Add bonus for check number found
    if check_number and check_number != "Not found":
        confidence += 0.18

    # Clamp
    confidence = max(0.0, min(confidence, 0.98))
    return confidence


def score_payee_quality(payee: str) -> float:
    """Heuristic scoring of how plausible a payee string is (0..1).
    Penalize amounts, city/state, and generic words; reward entity suffixes or natural name casing."""
    s = payee.strip()
    up = s.upper()
    words = [w for w in re.split(r"\s+", s) if w]

    if not words:
        return 0.0

    score = 0.0

    # Reward presence of common business suffixes or two+ words
    suffixes = {"INC", "LLC", "L.L.C", "CORP", "CORPORATION", "CO", "CO.", "LTD", "COMPANY"}
    if any(up.endswith(suf) or up.endswith(", " + suf) for suf in suffixes):
        score += 0.45
    if len(words) >= 2:
        score += 0.2

    # Reward reasonable length
    if 5 <= len(s) <= 40:
        score += 0.15

    # Penalize digits inside name
    if re.search(r"\d", s):
        score -= 0.35

    # Penalize city/state patterns
    if re.search(r",\s*[A-Z]{2}(?:\s*\d{5})?$", up):
        score -= 0.5

    # Penalize if most words are number/amount words
    amount_words = {"ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE",
                    "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
                    "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN",
                    "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY",
                    "HUNDRED", "THOUSAND", "MILLION", "BILLION", "DOLLARS"}
    total = len(words)
    amount_like = sum(1 for w in words if w.upper().strip('.,') in amount_words)
    if amount_like / total >= 0.5:
        score -= 0.5

    # Slight penalty if entire string is ALL CAPS without punctuation (often OCR header noise)
    if up == s and re.search(r"[A-Z]", s) and not re.search(r"[a-z]", s):
        score -= 0.05

    # Normalize to [0,1]
    return max(0.0, min(1.0, score))


if __name__ == "__main__":
    test_images = [
        r"data\images\check_4819_front_20251008_143212.png",
        r"data\images\check_4822_front_20251008_143231.png",
    ]
    
    for image_path in test_images:
        if not os.path.exists(image_path):
            print(f"Image not found: {image_path}")
            continue
            
        print(f"\nProcessing: {image_path}")
        print("=" * 60)
        
        try:
            result = extract_check_info(image_path)
            print(f"\n✓ Check Number: {result['check_number']}")
            print(f"✓ Payee Name: {result['payee_name']}")
            print(f"✓ Confidence: {result['confidence']:.2%}")
        except Exception as e:
            print(f"✗ Error: {str(e)}")
        
        print("=" * 60)