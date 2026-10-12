"""Categories derive from allowlisted event codes, never private payloads."""
def category(action):
    if action.startswith('material_'):return 'Materials'
    if action in ('assessment_generated','generate_quiz','generate_question_paper'):return 'Assessments'
    if action.startswith(('document_','preference_')) or action=='generate_document':return 'Documents'
    if action in ('batch_warnings','personalized_practice'):return 'Student Analytics'
    return 'Workspace'
CATEGORIES=('Materials','Assessments','Documents','Student Analytics','Workspace')
