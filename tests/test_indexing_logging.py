"""Development-only terminal logging; no storage or model work."""
import logging
from unittest.mock import Mock
import pytest
from indexing_diagnostics import LOGGER,development_logging,diagnostic_scope,observe
from fastapi.testclient import TestClient
from api.app import create_api_app
from api.settings import APISettings

@pytest.fixture(autouse=True)
def logger_state():
 old=(LOGGER.level,LOGGER.propagate,LOGGER.disabled,list(LOGGER.handlers))
 yield
 LOGGER.setLevel(old[0]);LOGGER.propagate=old[1];LOGGER.disabled=old[2]
 for h in list(LOGGER.handlers):
  if h not in old[3]:LOGGER.removeHandler(h);h.close()


def test_development_success_terminal(capsys):
 root_level=logging.getLogger().level
 with development_logging(True):
  with diagnostic_scope():observe(success=True,chunk_count=3)
 text=capsys.readouterr().err
 assert text.count('MATERIAL_INDEX')==1 and 'INFO:' in text and '"success": true' in text
 assert logging.getLogger().level==root_level


def test_failure_and_error_visible(capsys):
 with development_logging(True):
  with diagnostic_scope():observe(failed=True,exception_type='RuntimeError')
  LOGGER.error('MATERIAL_INDEX controlled_error')
 text=capsys.readouterr().err
 assert text.count('MATERIAL_INDEX')==2 and 'WARNING:' in text and 'ERROR:' in text


def test_no_duplicates_and_restore(capsys):
 old=(LOGGER.level,LOGGER.propagate,LOGGER.disabled,list(LOGGER.handlers))
 with development_logging(True):
  with development_logging(True):
   with diagnostic_scope():observe(success=True)
 assert capsys.readouterr().err.count('MATERIAL_INDEX')==1
 assert (LOGGER.level,LOGGER.propagate,LOGGER.disabled,list(LOGGER.handlers))==old


def test_production_no_configuration():
 old=(LOGGER.level,LOGGER.propagate,LOGGER.disabled,list(LOGGER.handlers))
 with development_logging(False):
  assert (LOGGER.level,LOGGER.propagate,LOGGER.disabled,list(LOGGER.handlers))==old


def test_sensitive_fields_dropped(capsys):
 with development_logging(True):
  with diagnostic_scope():observe(success=True,text='PRIVATE extracted text',filename='private.pdf',professor='PRIVATE identity',path='/private/storage',credentials='PRIVATE key',embeddings=[1,2])
 text=capsys.readouterr().err
 assert 'MATERIAL_INDEX' in text
 assert all(token not in text for token in ('PRIVATE','private.pdf','/private/','credentials','embeddings'))

@pytest.mark.parametrize('mode',['development','production'])
def test_api_lifespan_configuration(mode,capsys):
 app=create_api_app(settings=APISettings(mode=mode),services=Mock(),sessions=Mock())
 previous=(LOGGER.level,LOGGER.propagate,list(LOGGER.handlers))
 with TestClient(app):
  if mode=='development':
   assert LOGGER.getEffectiveLevel()==logging.INFO
   with diagnostic_scope():observe(success=True)
  else:assert (LOGGER.level,LOGGER.propagate,list(LOGGER.handlers))==previous
 assert (LOGGER.level,LOGGER.propagate,list(LOGGER.handlers))==previous
 text=capsys.readouterr().err
 assert text.count('MATERIAL_INDEX')==(1 if mode=='development' else 0)
