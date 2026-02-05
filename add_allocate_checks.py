#!/usr/bin/env python3
"""
Add stat=ierr error checking to all allocate() calls in Fortran source files.
Also ensures 'integer ierr' is declared in each routine that uses allocate.
"""

import re
import os
import sys

def find_allocate_files(directory):
    """Find all .f90 files with allocate( calls in them."""
    files = []
    for fname in sorted(os.listdir(directory)):
        if fname.endswith('.f90'):
            fpath = os.path.join(directory, fname)
            with open(fpath, 'r') as f:
                content = f.read()
            # Check for allocate( but not deallocate(
            if re.search(r'(?<![a-zA-Z])allocate\s*\(', content, re.IGNORECASE):
                files.append(fpath)
    return files

def get_indent(line):
    """Get the leading whitespace of a line."""
    match = re.match(r'^(\s*)', line)
    return match.group(1) if match else ''

def is_comment(line):
    """Check if line is a comment."""
    stripped = line.strip()
    return stripped.startswith('!') or stripped.startswith('c ') or stripped.startswith('C ') or stripped == ''

def is_deallocate(line):
    """Check if this is a deallocate call."""
    stripped = line.strip().lower()
    return 'deallocate' in stripped and 'allocate' in stripped

def has_stat(line):
    """Check if the allocate already has stat=."""
    return 'stat=' in line.lower()

def is_allocate_call(line):
    """Check if this line has an allocate( call that's NOT deallocate."""
    stripped = line.strip()
    # Skip comments
    if is_comment(stripped):
        return False
    # Skip deallocate
    lower = stripped.lower()
    if 'deallocate' in lower:
        return False
    # Check for allocate(
    if re.search(r'(?<![a-zA-Z])allocate\s*\(', lower):
        return True
    return False

def find_matching_paren(lines, start_idx, start_col):
    """Find the closing paren of an allocate call that may span multiple lines.
    Returns (end_line_idx, end_col) of the closing paren."""
    depth = 0
    for i in range(start_idx, len(lines)):
        line = lines[i]
        start = start_col if i == start_idx else 0
        for j in range(start, len(line)):
            if line[j] == '(':
                depth += 1
            elif line[j] == ')':
                depth -= 1
                if depth == 0:
                    return (i, j)
    return (start_idx, len(lines[start_idx]) - 1)

def process_file(filepath):
    """Process a single file to add stat=ierr to allocate calls."""
    with open(filepath, 'r') as f:
        lines = f.readlines()

    # Track which subroutine/function blocks need ierr declared
    # We'll collect line indices of allocate calls first
    allocate_lines = []

    # First pass: identify all allocate calls (including multi-line)
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip comments
        if is_comment(stripped):
            i += 1
            continue

        # Skip deallocate
        if is_deallocate(line):
            i += 1
            continue

        # Check for allocate(
        lower = stripped.lower()
        match = re.search(r'(?<![a-zA-Z])allocate\s*\(', lower)
        if match and not has_stat(line):
            # Find the allocate( in the original line
            orig_match = re.search(r'(?<![a-zA-Z])(allocate\s*\()', line, re.IGNORECASE)
            if orig_match:
                # Find where the opening paren is
                paren_pos = orig_match.end() - 1  # position of '('
                # Find matching close paren (may span lines)
                end_line, end_col = find_matching_paren(lines, i, paren_pos)
                allocate_lines.append((i, end_line, end_col))
                i = end_line + 1
                continue

        i += 1

    if not allocate_lines:
        return 0

    # Now we need to find all routine boundaries and check for ierr declarations
    # Find subroutine/function start lines and their variable declaration areas
    routine_starts = []  # (line_idx, name)

    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if is_comment(stripped):
            continue
        # Match subroutine or function declarations
        # Various patterns: subroutine name(...), function name(...), etc.
        m = re.match(r'\s*(recursive\s+)?(subroutine|function|program)\s+(\w+)', line, re.IGNORECASE)
        if m:
            routine_starts.append((idx, m.group(3)))

    # For each routine, find where to insert 'integer ierr' if needed
    # Also find if ierr is already declared

    # Map: routine_start_line -> (best_insert_line, already_has_ierr)
    routine_info = {}

    for rs_idx, (start_line, rname) in enumerate(routine_starts):
        # Determine the end of this routine's declaration section
        # Look for: implicit none, variable declarations, use statements
        # The declaration section ends at the first executable statement

        already_has_ierr = False
        last_decl_line = start_line

        # Scan from start_line forward
        in_continuation = False
        for j in range(start_line + 1, len(lines)):
            ln = lines[j].strip()
            ln_lower = ln.lower()

            if is_comment(ln) or ln == '':
                continue

            # Check if this line declares ierr
            if re.search(r'\bierr\b', ln_lower) and ('integer' in ln_lower or '::' in ln_lower):
                already_has_ierr = True

            # Check if this is still a declaration line
            is_decl = False

            # Common declaration patterns
            decl_patterns = [
                r'^\s*implicit\s+none',
                r'^\s*use\s+',
                r'^\s*integer',
                r'^\s*real',
                r'^\s*double\s+precision',
                r'^\s*character',
                r'^\s*logical',
                r'^\s*type\s*\(',
                r'^\s*class\s*\(',
                r'^\s*dimension\s',
                r'^\s*parameter\s',
                r'^\s*data\s+',
                r'^\s*save\s',
                r'^\s*external\s',
                r'^\s*intrinsic\s',
                r'^\s*include\s',
                r'^\s*#include',
                r'^\s*private\s',
                r'^\s*public\s',
                r'^\s*optional\s',
                r'^\s*intent\s',
                r'^\s*common\s',
                r'^\s*equivalence\s',
            ]

            for pat in decl_patterns:
                if re.match(pat, lines[j], re.IGNORECASE):
                    is_decl = True
                    break

            # Also check for continuation lines (& at end or beginning)
            if in_continuation:
                is_decl = True

            if lines[j].rstrip().endswith('&') or (ln.startswith('&')):
                in_continuation = True
            else:
                in_continuation = False

            if is_decl:
                last_decl_line = j
            else:
                # Check for end/contains/subroutine/function - means we left this routine
                if re.match(r'\s*(end\s|contains\s|subroutine\s|function\s)', ln_lower):
                    break
                # First non-declaration, non-comment line - this is where declarations end
                break

        routine_info[start_line] = (last_decl_line, already_has_ierr)

    # For each allocate call, find which routine it belongs to
    def find_routine_for_line(line_idx):
        best = None
        for (rs, rname) in routine_starts:
            if rs <= line_idx:
                if best is None or rs > best[0]:
                    best = (rs, rname)
        return best

    # Determine which routines need ierr added
    routines_needing_ierr = set()
    for (alloc_start, alloc_end, alloc_end_col) in allocate_lines:
        routine = find_routine_for_line(alloc_start)
        if routine:
            rs = routine[0]
            if rs in routine_info and not routine_info[rs][1]:
                routines_needing_ierr.add(rs)

    # Now build the modified file content
    # We need to:
    # 1. Insert 'integer ierr' declarations where needed
    # 2. Modify allocate calls to add stat=ierr
    # 3. Insert error check after each allocate call

    # Work backwards to avoid index shifting issues
    # First, collect all modifications

    modifications = []  # (line_idx, type, data)
    # type: 'insert_after' -> insert line after line_idx
    # type: 'modify_line' -> replace line_idx with new content
    # type: 'modify_range' -> replace lines from start to end

    # Add ierr declarations
    for rs in routines_needing_ierr:
        insert_after = routine_info[rs][0]
        # Determine indentation from the declaration area
        indent = get_indent(lines[insert_after])
        if not indent:
            indent = '\t'
        modifications.append(('insert_after', insert_after, indent + 'integer ierr\n'))

    # Modify allocate calls
    for (alloc_start, alloc_end, alloc_end_col) in allocate_lines:
        indent = get_indent(lines[alloc_start])

        if alloc_start == alloc_end:
            # Single-line allocate
            line = lines[alloc_start]
            # Find the closing paren position
            # Insert stat=ierr before the closing paren
            new_line = line[:alloc_end_col] + ',stat=ierr' + line[alloc_end_col:]
            modifications.append(('modify_line', alloc_start, new_line))
            # Insert error check after
            check_line = indent + "if( ierr /= 0 ) stop 'error stop: allocation failed'\n"
            modifications.append(('insert_after', alloc_start, check_line))
        else:
            # Multi-line allocate
            # Modify the line with the closing paren
            line = lines[alloc_end]
            new_line = line[:alloc_end_col] + ',stat=ierr' + line[alloc_end_col:]
            modifications.append(('modify_line', alloc_end, new_line))
            # Insert error check after the last line
            check_line = indent + "if( ierr /= 0 ) stop 'error stop: allocation failed'\n"
            modifications.append(('insert_after', alloc_end, check_line))

    # Apply modifications in reverse order to preserve line indices
    # Sort by line index descending, with inserts after modifies for same line
    # For same line: insert_after should come before modify_line when processing in reverse

    def sort_key(mod):
        line_idx = mod[1]
        # For reverse processing: higher line numbers first
        # For same line: insert_after should be applied after modify_line
        # But since we're reversing, insert_after should come first in the sorted list
        type_order = 0 if mod[0] == 'insert_after' else 1
        return (-line_idx, type_order)

    modifications.sort(key=sort_key)

    for mod in modifications:
        if mod[0] == 'modify_line':
            lines[mod[1]] = mod[2]
        elif mod[0] == 'insert_after':
            lines.insert(mod[1] + 1, mod[2])

    with open(filepath, 'w') as f:
        f.writelines(lines)

    return len(allocate_lines)

def main():
    src_dir = '/home/razinka/shyfem/src/shyfem'
    files = find_allocate_files(src_dir)

    total_allocates = 0

    # Priority files first
    priority = ['concentration.f90', 'hydrodynamic.f90', 'baroclinic.f90',
                'waves_admin.f90', 'turbine.f90']

    priority_files = []
    other_files = []

    for f in files:
        basename = os.path.basename(f)
        if basename in priority:
            priority_files.append(f)
        else:
            other_files.append(f)

    # Sort priority files in the specified order
    priority_files.sort(key=lambda f: priority.index(os.path.basename(f)) if os.path.basename(f) in priority else 999)

    all_files = priority_files + other_files

    for fpath in all_files:
        count = process_file(fpath)
        if count > 0:
            print(f"  {os.path.basename(fpath)}: {count} allocate calls modified")
            total_allocates += count

    print(f"\nTotal: {total_allocates} allocate calls modified across {len(all_files)} files")

if __name__ == '__main__':
    main()
