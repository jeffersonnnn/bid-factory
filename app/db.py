"""One SQLite database per operator organization. Source records are append-only."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f"{prefix}-{uuid4().hex[:12]}"


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_versions VALUES(1);
CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY, name TEXT NOT NULL);
INSERT OR IGNORE INTO organizations VALUES('local', 'Bid Factory');
CREATE TABLE IF NOT EXISTS companies(
 id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL, profile TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bids(
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), title TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'CREATED', revision INTEGER NOT NULL DEFAULT 0,
 draft_revision INTEGER, approved_revision INTEGER, controls TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), bid_id TEXT REFERENCES bids(id),
 name TEXT NOT NULL, kind TEXT NOT NULL, sequence INTEGER NOT NULL DEFAULT 0,
 sha256 TEXT NOT NULL, content BLOB NOT NULL, pages TEXT NOT NULL, warnings TEXT NOT NULL DEFAULT '[]',
 extracted INTEGER NOT NULL DEFAULT 0, reviewed INTEGER NOT NULL DEFAULT 0,
 acknowledged INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirements(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id), document_id TEXT NOT NULL REFERENCES documents(id),
 page INTEGER NOT NULL, locator TEXT NOT NULL, quote TEXT NOT NULL, text TEXT NOT NULL,
 kind TEXT NOT NULL, scope TEXT NOT NULL, mandatory INTEGER NOT NULL DEFAULT 1,
 key TEXT NOT NULL, constraints TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL,
 evaluation_factor TEXT NOT NULL DEFAULT '', component TEXT NOT NULL DEFAULT 'technical_volume',
 supersedes TEXT REFERENCES requirements(id), supersession_reason TEXT NOT NULL DEFAULT '',
 fingerprint TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id),
 document_id TEXT REFERENCES documents(id), bid_id TEXT REFERENCES bids(id),
 page INTEGER, locator TEXT NOT NULL, quote TEXT NOT NULL, statement TEXT NOT NULL,
 kind TEXT NOT NULL, fact_key TEXT NOT NULL, source_type TEXT NOT NULL,
 verified INTEGER NOT NULL DEFAULT 0, approved INTEGER NOT NULL DEFAULT 0,
 rejected INTEGER NOT NULL DEFAULT 0, expires_at TEXT, supersedes TEXT REFERENCES evidence(id),
 customer_name TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mappings(
 requirement_id TEXT NOT NULL REFERENCES requirements(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 approved INTEGER NOT NULL DEFAULT 0, rationale TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(requirement_id, evidence_id));
CREATE TABLE IF NOT EXISTS questions(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id),
 requirement_id TEXT NOT NULL UNIQUE REFERENCES requirements(id), text TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'OPEN');
CREATE TABLE IF NOT EXISTS answers(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id),
 requirement_id TEXT NOT NULL REFERENCES requirements(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 customer_name TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposal_sections(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id), revision INTEGER NOT NULL,
 requirement_id TEXT NOT NULL REFERENCES requirements(id), title TEXT NOT NULL, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS proposal_claims(
 id TEXT PRIMARY KEY, section_id TEXT NOT NULL REFERENCES proposal_sections(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id), text TEXT NOT NULL,
 claim_type TEXT NOT NULL, verification_status TEXT NOT NULL DEFAULT 'VERIFIED');
CREATE TABLE IF NOT EXISTS audit_runs(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id), revision INTEGER NOT NULL,
 content_hash TEXT NOT NULL, reviewer TEXT NOT NULL, mode TEXT NOT NULL, notes TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_findings(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES audit_runs(id), requirement_id TEXT,
 severity TEXT NOT NULL, rule_id TEXT NOT NULL, finding TEXT NOT NULL, action TEXT NOT NULL,
 resolved_revision INTEGER, resolution TEXT, resolved_by TEXT);
CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_runs(
 id TEXT PRIMARY KEY, bid_id TEXT REFERENCES bids(id), stage TEXT NOT NULL,
 status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_events(
 id TEXT PRIMARY KEY, bid_id TEXT REFERENCES bids(id), reviewer TEXT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL, duration_seconds INTEGER NOT NULL,
 revision INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exports(
 id TEXT PRIMARY KEY, bid_id TEXT NOT NULL REFERENCES bids(id), revision INTEGER NOT NULL,
 content_hash TEXT NOT NULL, final INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS company_documents AS SELECT * FROM documents WHERE bid_id IS NULL;
CREATE VIEW IF NOT EXISTS bid_documents AS SELECT * FROM documents WHERE bid_id IS NOT NULL;
CREATE VIEW IF NOT EXISTS company_facts AS SELECT * FROM evidence WHERE source_type='document';
CREATE VIEW IF NOT EXISTS solicitation_facts AS SELECT * FROM requirements WHERE kind IN ('deadline','page_limit','submission','eligibility');
CREATE INDEX IF NOT EXISTS requirements_bid ON requirements(bid_id);
CREATE INDEX IF NOT EXISTS evidence_company ON evidence(company_id);
CREATE INDEX IF NOT EXISTS documents_bid ON documents(bid_id);
CREATE TRIGGER IF NOT EXISTS immutable_requirement_update BEFORE UPDATE ON requirements BEGIN SELECT RAISE(ABORT,'Requirements are immutable. Add a sourced replacement.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_requirement_delete BEFORE DELETE ON requirements BEGIN SELECT RAISE(ABORT,'Requirement ledger cannot be deleted.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_document_delete BEFORE DELETE ON documents BEGIN SELECT RAISE(ABORT,'Source documents cannot be deleted.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_document_content BEFORE UPDATE OF content,pages,sha256,sequence,kind,company_id,bid_id ON documents BEGIN SELECT RAISE(ABORT,'Source content is immutable.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_evidence_content BEFORE UPDATE OF statement,quote,document_id,page,source_type,company_id,bid_id,supersedes ON evidence BEGIN SELECT RAISE(ABORT,'Evidence content is immutable.'); END;
"""


def connect():
    path = Path(os.getenv('BID_FACTORY_DB', str(ROOT / 'data' / 'bid-factory.sqlite3')))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=120)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=120000')
    return db


def init():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        rules = {
            'RULE-001': 'Every mandatory requirement remains in the source ledger.',
            'RULE-002': 'Every factual claim equals approved, traceable evidence.',
            'RULE-003': 'Final export requires a current audit and zero blockers.',
            'RULE-004': 'The confirmed deadline must remain in the future.',
            'RULE-005': 'Every required attachment must have a mapped file.',
            'RULE-006': 'The rendered proposal must meet the confirmed page limit.',
            'RULE-007': 'Amendments preserve explicit replacement lineage.',
            'RULE-008': 'Every amendment requires acknowledgment.',
            'RULE-009': 'Pricing requires a named customer answer.',
            'RULE-010': 'UEI requires approved company or customer evidence.',
            'RULE-011': 'Source coverage, uncertainty and contradictions require review.',
            'RULE-012': 'Every change invalidates the previous draft, audit and approval.',
        }
        db.executemany('INSERT OR IGNORE INTO rules VALUES(?,?)', rules.items())


@contextmanager
def transaction():
    db = connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def one(db, table, ident):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(404, f'{table} record not found')
    return dict(row)


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def insert(db, table, **values):
    db.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
    return values['id'] if 'id' in values else None


def event(db, bid_id, action, reviewer='operator', reason='', duration=0):
    revision = one(db, 'bids', bid_id)['revision'] if bid_id else None
    insert(db, 'review_events', id=uid('REV'), bid_id=bid_id, reviewer=reviewer,
           action=action, reason=reason, duration_seconds=duration, revision=revision, created_at=now())


def invalidate(db, bid_id, state='ANALYZED'):
    db.execute('UPDATE bids SET revision=revision+1, approved_revision=NULL, state=? WHERE id=?', (state, bid_id))


def invalidate_company(db, company_id):
    for bid in rows(db, 'SELECT id FROM bids WHERE company_id=?', (company_id,)):
        invalidate(db, bid['id'])
        db.execute('UPDATE mappings SET approved=0 WHERE requirement_id IN (SELECT id FROM requirements WHERE bid_id=?)', (bid['id'],))
