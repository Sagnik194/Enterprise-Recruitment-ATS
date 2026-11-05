"""Pure, explainable screening; missing information is never a rejection."""
def parse_skills(value):
    return {s.strip().casefold() for s in (value or '').split(',') if s.strip()}

def evaluate(profile, requirement):
    if requirement is None:
        return {'status': 'not_configured', 'reasons': ['Recruiter has not configured eligibility requirements']}
    missing = []
    failed = []
    if requirement.graduation_year_min is not None or requirement.graduation_year_max is not None:
        if profile is None or profile.graduation_year is None:
            missing.append('Graduation year is missing')
        elif requirement.graduation_year_min is not None and profile.graduation_year < requirement.graduation_year_min:
            failed.append('Graduation year is below the minimum')
        elif requirement.graduation_year_max is not None and profile.graduation_year > requirement.graduation_year_max:
            failed.append('Graduation year is above the maximum')
    if requirement.minimum_experience_months is not None:
        if profile is None or profile.experience_months is None:
            missing.append('Experience information is missing')
        elif profile.experience_months < requirement.minimum_experience_months:
            failed.append('Experience is below the required minimum')
    required = parse_skills(requirement.required_skills)
    if required:
        if profile is None or not profile.skills or not parse_skills(profile.skills):
            missing.append('Skills information is missing')
        else:
            absent = sorted(required - parse_skills(profile.skills))
            if absent:
                failed.append('Missing required skills: ' + ', '.join(absent))
    if failed:
        return {'status': 'not_eligible', 'reasons': failed + missing}
    if missing:
        return {'status': 'insufficient_information', 'reasons': missing}
    return {'status': 'eligible', 'reasons': ['All configured requirements satisfied']}
