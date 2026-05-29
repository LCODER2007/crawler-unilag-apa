"""
Migration script: Copy all data from local SQLite database (uraas.db)
to the production PostgreSQL database.
"""

import os
import sys
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import Base, Community, Collection, Author, Item, File, item_authors, item_collections

def migrate():
    # SQLite URL
    sqlite_url = "sqlite:///uraas.db"
    
    # Postgres URL (get from environment variable)
    postgres_url = os.getenv("DATABASE_URL")
    if not postgres_url:
        print("[ERR] DATABASE_URL environment variable is not set!")
        print("Please run this command with DATABASE_URL set, for example:")
        print("DATABASE_URL=postgresql://user:pass@host:port/dbname python scripts/migrate_sqlite_to_postgres.py")
        sys.exit(1)
        
    # Standardize Render's postgres:// prefix to postgresql:// if needed
    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql://", 1)

    print(f"Source SQLite database: {sqlite_url}")
    print(f"Destination PostgreSQL database: {postgres_url.split('@')[-1] if '@' in postgres_url else postgres_url}")
    print("\nInitializing connections...")
    
    sqlite_engine = create_engine(sqlite_url)
    postgres_engine = create_engine(postgres_url)
    
    SqliteSession = sessionmaker(bind=sqlite_engine)
    PostgresSession = sessionmaker(bind=postgres_engine)
    
    sqlite_session = SqliteSession()
    postgres_session = PostgresSession()
    
    try:
        print("Recreating destination database tables if they do not exist...")
        Base.metadata.create_all(bind=postgres_engine)
        
        print("Clearing existing data in PostgreSQL tables to prevent collisions...")
        # Order matters for foreign key constraints
        postgres_session.execute(text("TRUNCATE TABLE files, item_authors, item_collections, items, authors, collections, communities CASCADE"))
        postgres_session.commit()
        
        # 1. Migrate Communities
        print("Migrating Communities...")
        communities = sqlite_session.query(Community).all()
        for comm in communities:
            new_comm = Community(
                id=comm.id,
                name=comm.name,
                ror_id=comm.ror_id,
                institution=comm.institution,
                ror=comm.ror
            )
            postgres_session.add(new_comm)
        postgres_session.flush()
        print(f"  Migrated {len(communities)} communities.")
        
        # 2. Migrate Collections
        print("Migrating Collections...")
        collections = sqlite_session.query(Collection).all()
        for coll in collections:
            new_coll = Collection(
                id=coll.id,
                community_id=coll.community_id,
                name=coll.name,
                email_domains=coll.email_domains,
                keywords=coll.keywords
            )
            postgres_session.add(new_coll)
        postgres_session.flush()
        print(f"  Migrated {len(collections)} collections.")
        
        # 3. Migrate Authors
        print("Migrating Authors...")
        authors = sqlite_session.query(Author).all()
        for auth in authors:
            new_auth = Author(
                id=auth.id,
                name=auth.name,
                normalized_name=auth.normalized_name,
                profile_url=auth.profile_url,
                orcid=auth.orcid,
                ror=auth.ror
            )
            postgres_session.add(new_auth)
        postgres_session.flush()
        print(f"  Migrated {len(authors)} authors.")
        
        # 4. Migrate Items
        print("Migrating Items...")
        items = sqlite_session.query(Item).all()
        for item in items:
            new_item = Item(
                id=item.id,
                title=item.title,
                abstract=item.abstract,
                doi=item.doi,
                publication_date=item.publication_date,
                url=item.url,
                source_repository=item.source_repository,
                pdf_url=item.pdf_url,
                dc_title=item.dc_title,
                dc_date_issued=item.dc_date_issued,
                dc_identifier_uri=item.dc_identifier_uri,
                dc_identifier_doi=item.dc_identifier_doi,
                dc_description_provenance=item.dc_description_provenance,
                dc_rights=item.dc_rights,
                dc_type=item.dc_type,
                dc_language=item.dc_language,
                dc_subject=item.dc_subject,
                docid=item.docid,
                docid_assigned_at=item.docid_assigned_at,
                ror=item.ror,
                institution=item.institution,
                content_type=item.content_type,
                tk_label=item.tk_label,
                tk_community=item.tk_community,
                patent_id=item.patent_id,
                patent_date=item.patent_date,
                language_code=item.language_code,
                is_african_language=item.is_african_language,
                sdg_tags=item.sdg_tags,
                ai_keywords=item.ai_keywords,
                special_collection_score=item.special_collection_score,
                special_collection_categories=item.special_collection_categories,
                created_at=item.created_at
            )
            postgres_session.add(new_item)
        postgres_session.flush()
        print(f"  Migrated {len(items)} items.")
        
        # 5. Migrate Files
        print("Migrating Files...")
        files = sqlite_session.query(File).all()
        for file in files:
            new_file = File(
                id=file.id,
                item_id=file.item_id,
                file_path=file.file_path,
                sha256_hash=file.sha256_hash,
                access_policy=file.access_policy,
                downloaded_at=file.downloaded_at
            )
            postgres_session.add(new_file)
        postgres_session.flush()
        print(f"  Migrated {len(files)} files.")
        
        # 6. Migrate association tables (item_authors and item_collections)
        print("Migrating Item-Author associations...")
        item_author_rows = sqlite_session.execute(item_authors.select()).all()
        for row in item_author_rows:
            postgres_session.execute(
                item_authors.insert().values(item_id=row.item_id, author_id=row.author_id)
            )
        print(f"  Migrated {len(item_author_rows)} item-author mappings.")
            
        print("Migrating Item-Collection associations...")
        item_coll_rows = sqlite_session.execute(item_collections.select()).all()
        for row in item_coll_rows:
            postgres_session.execute(
                item_collections.insert().values(
                    item_id=row.item_id, 
                    collection_id=row.collection_id,
                    confidence_score=row.confidence_score
                )
            )
        print(f"  Migrated {len(item_coll_rows)} item-collection mappings.")
        
        postgres_session.commit()
        print("[SUCCESS] Data migrated to PostgreSQL successfully!")
        
        # Reset sequences in Postgres so future inserts don't collide
        print("Resetting PostgreSQL primary key sequences...")
        tables = ["communities", "collections", "authors", "items", "files"]
        for table in tables:
            postgres_session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1) + 1) FROM {table}"
            ))
        postgres_session.commit()
        print("[SUCCESS] Sequences advanced.")
        
    except Exception as e:
        print(f"[ERR] Migration failed: {e}")
        postgres_session.rollback()
        raise
    finally:
        sqlite_session.close()
        postgres_session.close()

if __name__ == "__main__":
    migrate()
