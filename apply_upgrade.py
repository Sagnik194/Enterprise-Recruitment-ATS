"""Apply additive recruiter job-details upgrade. Run from ATS project root."""
from pathlib import Path
import re

root=Path.cwd()
web=root/'app/web.py'
models=root/'app/phase7_models.py'
template=root/'app/templates/recruiter.html'
for p in (web,models,template):
    if not p.exists(): raise SystemExit(f'Missing {p}')

m=models.read_text(encoding='utf-8')
if 'employment_type:' in m: raise SystemExit('Upgrade already applied; no files changed.')
anchor='    required_skills: Mapped[str | None] = mapped_column(Text, nullable=True)'
if m.count(anchor)!=1: raise SystemExit('Unexpected JobRequirement model; no changes made.')
fields='''
    employment_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    openings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximum_experience_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligible_degrees: Mapped[str | None] = mapped_column(String(255), nullable=True)
    minimum_cgpa: Mapped[float | None] = mapped_column(sa.Numeric(4, 2), nullable=True)
    minimum_tenth_percentage: Mapped[float | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    minimum_twelfth_percentage: Mapped[float | None] = mapped_column(sa.Numeric(5, 2), nullable=True)
    maximum_active_backlogs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
'''
# Import Numeric without a new sqlalchemy alias.
fields=fields.replace('sa.Numeric(', 'Numeric(')
m=m.replace('from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint', 'from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint')
m=m.replace(anchor,anchor+fields)

w=web.read_text(encoding='utf-8')
start=w.find('@router.post("/web/jobs")')
end=w.find('@router.post("/web/jobs/{job_id}/{action}")',start)
if start<0 or end<0: raise SystemExit('Cannot find original create_job block; no changes made.')
if 'from app.phase7_models import JobRequirement' not in w:
    w=w.replace('from app.models import Application, Interview, Job, User','from app.models import Application, Interview, Job, User\nfrom app.phase7_models import JobRequirement')
newroute='''@router.post("/web/jobs")
def create_job(
    request: Request,
    title: str = Form(...), description: str = Form(...),
    location: str = Form(...), csrf: str = Form(...),
    employment_type: str = Form("full_time"), work_mode: str = Form("onsite"),
    department: str = Form(""), openings: int | None = Form(None),
    minimum_experience_months: int | None = Form(None),
    maximum_experience_months: int | None = Form(None),
    salary_min: Decimal | None = Form(None), salary_max: Decimal | None = Form(None),
    required_skills: str = Form(""), preferred_skills: str = Form(""),
    eligible_degrees: str = Form(""),
    graduation_year_min: int | None = Form(None),
    graduation_year_max: int | None = Form(None),
    minimum_cgpa: Decimal | None = Form(None),
    minimum_tenth_percentage: Decimal | None = Form(None),
    minimum_twelfth_percentage: Decimal | None = Form(None),
    maximum_active_backlogs: int | None = Form(None),
    application_deadline: str = Form(""),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")

    title, description, location = title.strip(), description.strip(), location.strip()
    department, required_skills = department.strip(), required_skills.strip()
    preferred_skills, eligible_degrees = preferred_skills.strip(), eligible_degrees.strip()
    if not 3 <= len(title) <= 150 or not 20 <= len(description) <= 10000 or not 2 <= len(location) <= 120:
        raise HTTPException(422, "Invalid job title, location or description")
    if employment_type not in {"full_time", "part_time", "internship", "contract"}:
        raise HTTPException(422, "Invalid employment type")
    if work_mode not in {"onsite", "hybrid", "remote"}:
        raise HTTPException(422, "Invalid work mode")
    if len(department) > 100 or len(required_skills) > 3000 or len(preferred_skills) > 3000 or len(eligible_degrees) > 255:
        raise HTTPException(422, "Text field is too long")
    if openings is not None and not 1 <= openings <= 100000:
        raise HTTPException(422, "Openings must be between 1 and 100000")
    for value in (minimum_experience_months, maximum_experience_months):
        if value is not None and not 0 <= value <= 600:
            raise HTTPException(422, "Experience must be between 0 and 600 months")
    if (minimum_experience_months is not None and maximum_experience_months is not None
            and minimum_experience_months > maximum_experience_months):
        raise HTTPException(422, "Minimum experience exceeds maximum experience")
    for value in (salary_min, salary_max):
        if value is not None and (not value.is_finite() or not 0 <= value <= Decimal("9999999999.99")):
            raise HTTPException(422, "Invalid salary")
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise HTTPException(422, "Minimum salary exceeds maximum salary")
    for year in (graduation_year_min, graduation_year_max):
        if year is not None and not 1950 <= year <= 2200:
            raise HTTPException(422, "Invalid graduation year")
    if (graduation_year_min is not None and graduation_year_max is not None
            and graduation_year_min > graduation_year_max):
        raise HTTPException(422, "Invalid graduation year range")
    if minimum_cgpa is not None and (not minimum_cgpa.is_finite() or not 0 <= minimum_cgpa <= 10):
        raise HTTPException(422, "CGPA must be between 0 and 10")
    for value in (minimum_tenth_percentage, minimum_twelfth_percentage):
        if value is not None and (not value.is_finite() or not 0 <= value <= 100):
            raise HTTPException(422, "Percentages must be between 0 and 100")
    if maximum_active_backlogs is not None and not 0 <= maximum_active_backlogs <= 100:
        raise HTTPException(422, "Invalid active backlog limit")
    deadline = None
    if application_deadline.strip():
        try:
            deadline = datetime.strptime(application_deadline.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, "Invalid application deadline")
        if deadline.date() < datetime.now(timezone.utc).date():
            raise HTTPException(422, "Application deadline cannot be in the past")

    job = Job(title=title, description=description, location=location,
              recruiter_id=user.id, status="open", salary_min=salary_min, salary_max=salary_max)
    try:
        db.add(job)
        db.flush()
        db.add(JobRequirement(
            job_id=job.id, employment_type=employment_type, work_mode=work_mode,
            department=department or None, openings=openings,
            minimum_experience_months=minimum_experience_months,
            maximum_experience_months=maximum_experience_months,
            required_skills=required_skills or None,
            preferred_skills=preferred_skills or None,
            eligible_degrees=eligible_degrees or None,
            graduation_year_min=graduation_year_min,
            graduation_year_max=graduation_year_max,
            minimum_cgpa=minimum_cgpa,
            minimum_tenth_percentage=minimum_tenth_percentage,
            minimum_twelfth_percentage=minimum_twelfth_percentage,
            maximum_active_backlogs=maximum_active_backlogs,
            application_deadline=deadline,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return redirect(notice="job_created")


'''
w=w[:start]+newroute+w[end:]
# Query requirements in both dashboards, without changing existing context contract.
w=w.replace('return render(request, "candidate.html", user=user, jobs=jobs,', '''requirements = {r.job_id: r for r in db.scalars(
            select(JobRequirement).where(JobRequirement.job_id.in_([j.id for j in jobs]))
        ).all()} if jobs else {}
        return render(request, "candidate.html", requirements=requirements, user=user, jobs=jobs,''')
w=w.replace('return render(request, "recruiter.html", user=user, jobs=jobs,', '''requirements = {r.job_id: r for r in db.scalars(
            select(JobRequirement).where(JobRequirement.job_id.in_([j.id for j in jobs]))
        ).all()} if jobs else {}
        return render(request, "recruiter.html", requirements=requirements, user=user, jobs=jobs,''')

html=template.read_text(encoding='utf-8')
start=html.find('<section class="card mb-4">')
end=html.find('<h4>My Jobs</h4>',start)
if start<0 or end<0: raise SystemExit('Unexpected recruiter template; no changes made.')
form='''<section class="card mb-4"><div class="card-body">
<h4>Post a Job</h4>
<p class="text-muted">Fill in the job information and eligibility criteria. Optional fields may be left blank.</p>
<form action="/web/jobs" method="post" class="row g-3">
<input type="hidden" name="csrf" value="{{ csrf }}">
<div class="col-md-6"><label class="form-label">Job title *</label><input name="title" class="form-control" minlength="3" maxlength="150" required></div>
<div class="col-md-6"><label class="form-label">Location *</label><input name="location" class="form-control" minlength="2" maxlength="120" required></div>
<div class="col-md-4"><label class="form-label">Employment type</label><select name="employment_type" class="form-select"><option value="full_time">Full-time</option><option value="part_time">Part-time</option><option value="internship">Internship</option><option value="contract">Contract</option></select></div>
<div class="col-md-4"><label class="form-label">Work mode</label><select name="work_mode" class="form-select"><option value="onsite">On-site</option><option value="hybrid">Hybrid</option><option value="remote">Remote</option></select></div>
<div class="col-md-4"><label class="form-label">Department</label><input name="department" maxlength="100" class="form-control" placeholder="Engineering"></div>
<div class="col-md-4"><label class="form-label">Number of openings</label><input name="openings" type="number" min="1" max="100000" class="form-control"></div>
<div class="col-md-4"><label class="form-label">Minimum experience (months)</label><input name="minimum_experience_months" type="number" min="0" max="600" class="form-control" placeholder="0 for fresher"></div>
<div class="col-md-4"><label class="form-label">Maximum experience (months)</label><input name="maximum_experience_months" type="number" min="0" max="600" class="form-control"></div>
<div class="col-md-6"><label class="form-label">Minimum annual salary (₹)</label><input name="salary_min" type="number" step="0.01" min="0" class="form-control"></div>
<div class="col-md-6"><label class="form-label">Maximum annual salary (₹)</label><input name="salary_max" type="number" step="0.01" min="0" class="form-control"></div>
<div class="col-md-6"><label class="form-label">Required skills (comma-separated)</label><textarea name="required_skills" maxlength="3000" class="form-control" rows="2" placeholder="Python, FastAPI, SQL"></textarea></div>
<div class="col-md-6"><label class="form-label">Preferred skills (comma-separated)</label><textarea name="preferred_skills" maxlength="3000" class="form-control" rows="2" placeholder="Docker, AWS"></textarea></div>
<div class="col-md-6"><label class="form-label">Eligible degrees</label><input name="eligible_degrees" maxlength="255" class="form-control" placeholder="B.Tech, B.E., MCA"></div>
<div class="col-md-3"><label class="form-label">Graduation year from</label><input name="graduation_year_min" type="number" min="1950" max="2200" class="form-control"></div>
<div class="col-md-3"><label class="form-label">Graduation year to</label><input name="graduation_year_max" type="number" min="1950" max="2200" class="form-control"></div>
<div class="col-md-3"><label class="form-label">Minimum CGPA (out of 10)</label><input name="minimum_cgpa" type="number" min="0" max="10" step="0.01" class="form-control"></div>
<div class="col-md-3"><label class="form-label">Minimum 10th %</label><input name="minimum_tenth_percentage" type="number" min="0" max="100" step="0.01" class="form-control"></div>
<div class="col-md-3"><label class="form-label">Minimum 12th %</label><input name="minimum_twelfth_percentage" type="number" min="0" max="100" step="0.01" class="form-control"></div>
<div class="col-md-3"><label class="form-label">Maximum active backlogs</label><input name="maximum_active_backlogs" type="number" min="0" max="100" class="form-control"></div>
<div class="col-md-4"><label class="form-label">Application deadline (UTC date)</label><input name="application_deadline" type="date" class="form-control"></div>
<div class="col-12"><label class="form-label">Description *</label><textarea name="description" class="form-control" minlength="20" maxlength="10000" rows="4" required placeholder="Responsibilities, requirements, benefits and selection process"></textarea></div>
<div class="col-12"><button class="btn btn-primary">Publish Job</button></div>
</form></div></section>
'''
html=html[:start]+form+html[end:]
# Show additional details in existing recruiter job rows without altering other tables.
html=html.replace('<td>{{ j.title }}</td>', '''<td><strong>{{ j.title }}</strong>{% set r = requirements.get(j.id) %}{% if r %}
<div class="small text-muted">{{ (r.employment_type or 'full_time')|replace('_',' ')|title }} · {{ (r.work_mode or 'onsite')|title }}{% if r.openings %} · {{ r.openings }} openings{% endif %}</div>
{% if r.required_skills %}<div class="small">Skills: {{ r.required_skills }}</div>{% endif %}
{% if r.minimum_experience_months is not none %}<div class="small">Experience: {{ r.minimum_experience_months }}+ months</div>{% endif %}
{% if r.application_deadline %}<div class="small">Deadline: {{ r.application_deadline.strftime('%d %b %Y') }}</div>{% endif %}
{% endif %}</td>''',1)

# Write only after all structural checks pass.
for path,contents in ((models,m),(web,w),(template,html)):
    path.with_suffix(path.suffix+'.pre_advanced_jobs.bak').write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
    path.write_text(contents,encoding='utf-8')
print('Updated app/phase7_models.py, app/web.py, app/templates/recruiter.html')
