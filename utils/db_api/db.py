from loguru import logger
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session


class DB:
    def __init__(self, db_url: str, **kwargs):
        """
        Initializes a class.

        :param str db_url: a URL containing all the necessary parameters to connect to a DB
        """
        self.db_url = db_url
        self.engine = create_engine(self.db_url, **kwargs)
        self.Base = None
        self.s: Session = Session(bind=self.engine)
        self.conn = self.engine.connect()

    def create_tables(self, base):
        """
        Creates tables.

        :param base: a base class for declarative class definitions
        """
        self.Base = base
        self.Base.metadata.create_all(self.engine)

    def all(self, entities=None, *criterion, stmt=None) -> list:
        """
        Fetches all rows.

        :param entities: an ORM entity
        :param stmt: stmt
        :param criterion: criterion for rows filtering
        :return list: the list of rows
        """
        if stmt is not None:
            return list(self.s.scalars(stmt).all())

        if entities and criterion:
            return self.s.query(entities).filter(*criterion).all()

        if entities:
            return self.s.query(entities).all()

        return []

    def one(self, entities=None, *criterion, stmt=None, from_the_end: bool = False):
        """
        Fetches one row.

        :param entities: an ORM entity
        :param stmt: stmt
        :param criterion: criterion for rows filtering
        :param from_the_end: get the row from the end
        :return list: found row or None
        """
        if entities and criterion:
            rows = self.all(entities, *criterion)
        else:
            rows = self.all(stmt=stmt)

        if rows:
            if from_the_end:
                return rows[-1]

            return rows[0]

        return None

    def execute(self, query, *args):
        """
        Executes SQL query.

        :param query: the query
        :param args: any additional arguments
        """
        result = self.conn.execute(text(query), *args)
        self.commit()
        return result

    def commit(self):
        """
        Commits changes.
        """
        try:
            self.s.commit()

        except DatabaseError as e:
            logger.error(e)
            self.s.rollback()

    def insert(self, row: object | list[object]):
        """
        Inserts rows.

        :param Union[object, list[object]] row: an ORM entity or list of entities
        """
        if isinstance(row, list):
            self.s.add_all(row)

        elif isinstance(row, object):
            self.s.add(row)

        else:
            raise ValueError('Wrong type!')

        self.commit()

    def add_column_to_table(self, table_name: str, column_name: str, column_type: str, default_value=None):
        """
        Adds a column to an existing table in the database.

        :param str table_name: the name of the table
        :param str column_name: the name of the new column
        :param str column_type: the type of the new column
        :param default_value: the default value for the new column (optional)
        """
        inspector = inspect(self.engine)
        columns = [col['name'] for col in inspector.get_columns(table_name)]

        if column_name in columns:
            logger.warning(f"Column '{column_name}' already exists in table '{table_name}'.")
            return

        try:
            # Формируем SQL-запрос для добавления колонки
            alter_table_query = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"

            # Устанавливаем только DEFAULT, если оно задано
            if default_value is not None:
                alter_table_query += f" DEFAULT '{default_value}'" if isinstance(default_value,
                                                                                 str) else f" DEFAULT {default_value}"

            with self.engine.connect() as connection:
                connection.execute(text(alter_table_query))
                logger.success(f"Column '{column_name}' added to table '{table_name}'.")
        except DatabaseError as e:
            logger.error(f"Error adding column '{column_name}' to table '{table_name}': {e}")

