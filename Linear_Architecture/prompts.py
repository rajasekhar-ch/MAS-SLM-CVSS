from langchain_core.prompts import PromptTemplate


extract_resume_prompt = PromptTemplate(
            input_variables=["resume_text"],
            template="""

Role: You are a resume parsing agent. Your task is to analyze the provided resume text and extract structured information into a predefined JSON format.

Instructions:
        Analyze the following resume text and extract information into the
        JSON structure below.
        Be precise and extract ONLY information that is explicitly present
        in the resume.
        For missing or unavailable information, use null.
        Do not invent, infer, or guess information.
        Do not generate any code just generate final JSON output.
        Return ONLY the JSON object.
        Do not use markdown code fences.
        Do not add explanations.        
        Populate "links" with only web URLs (strings starting with http:// or https://, e.g. portfolio, GitHub, LinkedIn, project links), deduplicated. Do not put email addresses or phone numbers in "links" — those belong only in personal_information.
        If any additional textual information present in the resume that does not fit to any of the predefined fields , preserve that information in "other_info" field rather than discarding it.
        For each certification, populate "certificate_id" only if the resume explicitly states a certificate, license, or credential ID/number for it; otherwise leave it null.


Resume Text:
        '''
        {resume_text}
        '''

Use this exact structure to generate the JSON output:

        {{
        "personal_information": {{
            "name": null,
            "email": null,
            "phone": null,
            "location": null,
            "linkedin": null
        }},

        "professional_summary": {{
            "summary": null
        }},

        "education": [
            {{
            "degree": null,
            "field_of_study": null,
            "institution": null,
            "graduation_year": null,
            "gpa": null
            }}
        ],

        "experience": [
            {{
            "job_title": null,
            "company": null,
            "location": null,
            "start_date": null,
            "end_date": null,
            "duration_months": null,
            "responsibilities": [],
            "achievements": []
            }}
        ],

        "skills": {{
            "technical_skills": [],
            "soft_skills": [],
            "programming_languages": [],
            "tools_and_frameworks": []
        }},

        "certifications": [
            {{
            "certification_name": null,
            "issuer": null,
            "certificate_id": null,
            "date_obtained": null,
            "expiry_date": null
            }}
        ],

        "projects": [
            {{
            "project_name": null,
            "description": null,
            "technologies": [],
            "url": null
            }}
        ],

        "languages": [
            {{
            "language_name": null,
            "proficiency_level": null
            }}
        ],

        "publications_and_awards": [
            {{
            "title": null,
            "description": null,
            "date": null
            }}
        ],

        "links": [],
 
        "other_info": null
        }}
""",
)
 