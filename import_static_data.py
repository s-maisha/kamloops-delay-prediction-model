import os
import csv
import sqlite3
import glob

TABLE_CONSTRAINTS = {
    "agency": {
        "primary_key": ["agency_id"],
    },
    "calendar_dates": {
        "primary_key": ["service_id", "date"],
    },
    "routes": {
        "primary_key": ["route_id"],
    },
    "shapes": {
        "primary_key": ["shape_id", "shape_pt_sequence"],
    },
    "stops": {
        "primary_key": ["stop_id"],
    },
    "stop_times": {
        "primary_key": ["trip_id", "stop_sequence"],
        "foreign_keys": [
            ("trip_id", "trips", "trip_id"),
            ("stop_id", "stops", "stop_id")
        ]
    },
    "trips": {
        "primary_key": ["trip_id"],
        "foreign_keys": [
            ("route_id", "routes", "route_id")
        ]
    }
}

def detect_type(val):
    if val == "":
        return None
    try:
        int(val)
        return int
    except ValueError:
        try:
            float(val)
            return float
        except ValueError:
            return str

def process_file(db_path, file_path):
    table_name = os.path.splitext(os.path.basename(file_path))[0]
    print(f"Processing {file_path} -> table '{table_name}'...")
    
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        if not headers:
            print(f"Empty file: {file_path}")
            return
        
        # Clean headers by stripping whitespace
        headers = [h.strip() for h in headers]
        
        # Read all rows to determine types and collect data
        rows = list(reader)
        
        # Determine column types
        col_types = []
        for col_idx in range(len(headers)):
            has_int = False
            has_float = False
            has_str = False
            for row in rows:
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    if val == "":
                        continue
                    t = detect_type(val)
                    if t is int:
                        has_int = True
                    elif t is float:
                        has_float = True
                    elif t is str:
                        has_str = True
            
            if has_str:
                col_types.append("TEXT")
            elif has_float:
                col_types.append("REAL")
            elif has_int:
                col_types.append("INTEGER")
            else:
                col_types.append("TEXT") # default if all are empty
        
        # Connect to DB
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Drop existing table if any
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        
        # Create Table
        cols_def_list = [f'"{h}" {t}' for h, t in zip(headers, col_types)]
        
        # Add primary and foreign keys if necessary
        constraints = TABLE_CONSTRAINTS.get(table_name, {})
        pk_fields = constraints.get("primary_key", [])
        if pk_fields and all(field in headers for field in pk_fields):
            pk_cols = ", ".join([f'"{f}"' for f in pk_fields])
            cols_def_list.append(f"PRIMARY KEY ({pk_cols})")
            
        fk_defs = constraints.get("foreign_keys", [])
        for local_col, ref_table, ref_col in fk_defs:
            if local_col in headers:
                cols_def_list.append(
                    f'FOREIGN KEY ("{local_col}") REFERENCES "{ref_table}" ("{ref_col}")'
                )
                
        cols_def = ", ".join(cols_def_list)
        create_sql = f'CREATE TABLE "{table_name}" ({cols_def})'
        cursor.execute(create_sql)
        
        # Insert Data
        placeholders = ", ".join(["?"] * len(headers))
        insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
        
        processed_rows = []
        for row in rows:
            row_data = [val.strip() if val.strip() != "" else None for val in row]
            if len(row_data) < len(headers):
                row_data += [None] * (len(headers) - len(row_data))
            elif len(row_data) > len(headers):
                row_data = row_data[:len(headers)]
            processed_rows.append(row_data)
            
        cursor.executemany(insert_sql, processed_rows)
        conn.commit()
        
        # Create indexes for common key fields to optimize queries
        indexed_fields = ["trip_id", "stop_id", "route_id", "shape_id", "service_id"]
        for field in indexed_fields:
            if field in headers:
                index_name = f"idx_{table_name}_{field}"
                cursor.execute(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ("{field}")')
        
        conn.commit()
        conn.close()
        print(f"Imported {len(rows)} rows into '{table_name}'.")

def main():
    db_path = "gtfs.db"
    static_data_dir = "static-data"
    
    # Check if static-data folder exists
    if not os.path.exists(static_data_dir):
        print(f"Error: {static_data_dir} directory not found.")
        return
    
    files = glob.glob(os.path.join(static_data_dir, "*.txt"))
    if not files:
        print("No .txt files found in static-data.")
        return
    
    for f in sorted(files):
        process_file(db_path, f)
        
    # Verify foreign key integrity
    print("Verifying foreign key integrity...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_key_check")
    violations = cursor.fetchall()
    if violations:
        print("Warning: Foreign key violations detected:")
        for violation in violations:
            print(f"  Table '{violation[0]}' rowid {violation[1]} violates constraint with referenced table '{violation[2]}' (referenced rowid/key not found)")
    else:
        print("Foreign key integrity check passed successfully!")
    conn.close()
        
    print(f"Done! Database saved to '{db_path}'.")

if __name__ == "__main__":
    main()
