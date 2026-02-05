import os
import google.generativeai as genai

api_key = "AIzaSyCr1Dn5U5WJjMVwbyyhVCnQr4Lk8ON-dVw"
genai.configure(api_key=api_key)

print("Listing models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
except Exception as e:
    print(e)
