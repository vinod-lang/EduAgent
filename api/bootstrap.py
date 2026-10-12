"""Explicit synthetic development provisioning. Never invoked by app startup."""
import argparse,json,uuid
from pathlib import Path

def bootstrap(path):
    path=Path(path).resolve()
    if path.name=='eduagent.db' or 'chroma_db' in path.parts:raise ValueError('Use separate development API storage.')
    path.parent.mkdir(parents=True,exist_ok=True)
    from application.runtime import initialize_development_storage
    from security.repository import SecurityRepository
    from security.models import ProfessorIdentity
    from security.sessions import SessionService
    initialize_development_storage(path)
    repository=SecurityRepository(database_path=path);repository.initialize();SessionService(repository).initialize()
    institution,department=str(uuid.uuid4()),str(uuid.uuid4());identities={}
    for alias in ('professor-a','professor-b'):
        identity=str(uuid.uuid4());repository.bootstrap_professor(ProfessorIdentity(identity,'Development '+alias,institution,department));identities[alias]=identity
    return identities

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Seed fictional DEVELOPMENT AUTH ONLY identities in separate local storage.')
    parser.add_argument('--database',required=True)
    args=parser.parse_args()
    print(json.dumps(bootstrap(args.database))) # opaque IDs only, no session credentials
