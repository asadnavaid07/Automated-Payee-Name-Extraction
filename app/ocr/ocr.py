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
    payee_name = "Not found"
    
    if texts:
        word_boxes = []
        for text in texts[1:]: 
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
                "center_y": center_y,
                "height": height
            })
        
        phrase_candidates = [
            "PAY TO THE ORDER OF", "PAY TO THE OF", "PAY TO THE",
            "TO THE ORDER OF", "TO THE OF", "ORDER OF", "TO THE", "PAY"
        ]
        
        phrase_boxes = []
        for candidate in phrase_candidates:
            for wb in word_boxes:
                if wb["desc"].upper() == candidate.upper():
                    phrase_boxes.append(wb)
        if phrase_boxes:
            phrase_box = max(phrase_boxes, key=lambda wb: wb["max_x"])  
            phrase_box = None
        
        if phrase_box:
            phrase_max_x = phrase_box["max_x"]
            phrase_center_y = phrase_box["center_y"]
            tolerance = phrase_box["height"] * 1.5 
            
            payee_words = []
            exclude_phrases = {"PAY", "TO", "THE", "ORDER", "OF", "FOR", "DOLLARS"}
            for wb in word_boxes:
                if (abs(wb["center_y"] - phrase_center_y) < tolerance and
                    wb["min_x"] > phrase_max_x and
                    not any(wb["desc"].upper().startswith(p) for p in exclude_phrases)):
                    payee_words.append(wb)
            
            if payee_words:
                payee_words.sort(key=lambda w: w["min_x"])
                
                payee_parts = []
                for w in payee_words:
                    if w["desc"].startswith('$') or re.match(r'^\d+[.,]?\d*', w["desc"]):
                        break  
                    payee_parts.append(w["desc"])
                payee_name = ' '.join(payee_parts).strip()

    if payee_name == "Not found":
        normalized_text = ' '.join(full_text.split())
        payee_pattern = r"(?:PAY TO THE ORDER OF|PAY TO THE OF|PAY TO THE)\s*([\w\s&.,'()-]+?)\s*(?=\$|\d|EIGHT|DOLLARS|$)"
        payee_match = re.search(payee_pattern, normalized_text, re.IGNORECASE)
        payee_name = payee_match.group(1).strip() if payee_match else "Not found"

    check_number = "Not found"
    for text in texts[1:]:  
        description = text.get("description", "")
        vertices = text.get("boundingPoly", {}).get("vertices", [])
        if len(vertices) < 2:
            continue

        min_x = min(v.get("x", 0) for v in vertices)
        min_y = min(v.get("y", 0) for v in vertices)
        max_x = max(v.get("x", 0) for v in vertices)

        if (re.match(r'^\d{3,5}$', description) and 
            min_y < 150 and  
            max_x > 700 and  
            min_x > 600):   
            check_number = description
            break

    if check_number == "Not found":
        for text in texts[1:]:
            description = text.get("description", "")
            vertices = text.get("boundingPoly", {}).get("vertices", [])
            if len(vertices) < 2:
                continue
            min_y = min(v.get("y", 0) for v in vertices)
            max_x = max(v.get("x", 0) for v in vertices)
            if (re.match(r'^\d{4}$', description) and 
                min_y < 200 and 
                max_x > 600):
                check_number = description
                break

    if check_number == "Not found":
        date_line = re.search(r"DATE\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s*(\d{3,5})", full_text)
        if date_line:
            check_number = date_line.group(2)

    if check_number == "Not found":
        check_match = re.search(r"\b\d{4}\b", full_text)
        if check_match:
            check_number = check_match.group(0)

    return {
        "check_number": check_number,
        "payee_name": payee_name,
    }

if __name__ == "__main__":
    image_path = "app\ocr\images\image3.png" 
    result = extract_check_info(image_path)
    print(f"Check Number: {result['check_number']}")
    print(f"Payee Name: {result['payee_name']}")