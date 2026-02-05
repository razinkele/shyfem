#!/usr/bin/env python3
"""
Add stat=ierr error checking to all allocate() calls in specified Fortran files.
More robust version that carefully handles Fortran structure.
"""

import re
import sys

def find_routines(lines):
    """Find all subroutine/function boundaries.
    Returns list of (start_line, name, end_line) tuples.
    """
    routines = []
    stack = []  # stack of (start_line, name, type)
    # type can be 'routine', 'module', 'if', 'do', 'select', 'type', 'interface'

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('!'):
            i += 1
            continue

        # Remove inline comments
        # Be careful about strings - simple approach: find ! not in quotes
        code = strip_comment(stripped).lower().strip()

        if not code:
            i += 1
            continue

        # Check for module/contains - skip module-level, only track routines
        if re.match(r'^module\s+\w+', code) and not re.match(r'^module\s+procedure', code):
            stack.append((i, 'module', 'module'))
            i += 1
            continue

        if re.match(r'^end\s+module', code) or (code == 'end' and stack and stack[-1][2] == 'module'):
            if stack and stack[-1][2] == 'module':
                stack.pop()
            i += 1
            continue

        # Check for interface blocks
        if re.match(r'^(abstract\s+)?interface\b', code):
            stack.append((i, 'interface', 'interface'))
            i += 1
            continue

        if re.match(r'^end\s+interface', code):
            if stack and stack[-1][2] == 'interface':
                stack.pop()
            i += 1
            continue

        # Check for type definitions
        if re.match(r'^type\s+\w+', code) and not re.match(r'^type\s*\(', code):
            stack.append((i, 'type_def', 'type_def'))
            i += 1
            continue

        if re.match(r'^end\s+type', code):
            if stack and stack[-1][2] == 'type_def':
                stack.pop()
            i += 1
            continue

        # Skip if inside interface block
        if stack and stack[-1][2] == 'interface':
            i += 1
            continue

        # Check for subroutine/function start
        m = re.match(r'^(?:recursive\s+)?(?:integer|real|logical|double\s+precision|character\S*\s+)?\s*(?:subroutine|function)\s+(\w+)', code)
        if m:
            rname = m.group(1)
            stack.append((i, rname, 'routine'))
            i += 1
            continue

        # Check for end of routine
        # "end", "end subroutine", "end subroutine name", "end function", "end function name"
        m_end = re.match(r'^end\s*(subroutine|function)?\s*(\w*)\s*$', code)
        if m_end:
            end_type = m_end.group(1)
            if end_type in ('subroutine', 'function'):
                # Explicit end of routine
                if stack and stack[-1][2] == 'routine':
                    start_line, name, _ = stack.pop()
                    routines.append((start_line, name, i))
            elif end_type is None and code.strip() == 'end':
                # bare 'end' - ends innermost routine or module
                if stack and stack[-1][2] == 'routine':
                    start_line, name, _ = stack.pop()
                    routines.append((start_line, name, i))
            i += 1
            continue

        i += 1

    return routines


def strip_comment(line):
    """Strip inline comment from a Fortran line (simple approach)."""
    in_string = False
    string_char = None
    for i, ch in enumerate(line):
        if in_string:
            if ch == string_char:
                in_string = False
        else:
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
            elif ch == '!':
                return line[:i]
    return line


def find_declaration_end(lines, start, end):
    """Find the line number of the last declaration in a routine.
    Returns the line number after which to insert new declarations.
    """
    # Skip the subroutine/function signature (may span multiple lines)
    i = start

    # Skip past the signature (handle continuation lines)
    # The signature line contains 'subroutine' or 'function'
    while i <= end:
        line = lines[i].rstrip()
        if line.endswith('&'):
            i += 1
            continue
        break
    i += 1  # move past the last line of signature

    last_decl = None

    while i <= end:
        stripped = lines[i].strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith('!'):
            i += 1
            continue

        code = strip_comment(stripped).lower().strip()
        if not code:
            i += 1
            continue

        # Check if this is a continuation line (starts with &)
        if code.startswith('&'):
            if last_decl is not None:
                last_decl = i
            i += 1
            continue

        # Check if it's a declaration
        is_decl = False

        # use statements
        if re.match(r'^use\s+', code):
            is_decl = True
        # implicit
        elif re.match(r'^implicit\s+', code):
            is_decl = True
        # include
        elif re.match(r'^include\s+', code):
            is_decl = True
        # Type declarations
        elif re.match(r'^(integer|real|double\s+precision|logical|character|complex|type\s*\()', code):
            is_decl = True
        # Special: allocatable, dimension, pointer, target, save, parameter
        elif re.match(r'^(allocatable|dimension|pointer|target|save|parameter)\b', code):
            is_decl = True
        # DATA statements
        elif re.match(r'^data\s+', code):
            is_decl = True
        # EQUIVALENCE
        elif re.match(r'^equivalence\s+', code):
            is_decl = True
        # EXTERNAL
        elif re.match(r'^external\s+', code):
            is_decl = True
        # INTRINSIC
        elif re.match(r'^intrinsic\s+', code):
            is_decl = True

        if is_decl:
            last_decl = i
            # Handle continuation
            while i <= end and lines[i].rstrip().endswith('&'):
                i += 1
                last_decl = i
            i += 1
        else:
            # Hit executable code
            break

    return last_decl


def has_ierr_decl(lines, start, end):
    """Check if a routine already has an 'ierr' variable declaration."""
    for i in range(start, end+1):
        stripped = lines[i].strip()
        if stripped.startswith('!'):
            continue
        code = strip_comment(stripped).lower()
        # Check for integer declaration containing ierr
        if re.match(r'.*\binteger\b.*\bierr\b', code):
            return True
    return False


def find_allocate_lines(lines, start, end):
    """Find all allocate() calls (not deallocate, not commented) without stat=."""
    result = []
    for i in range(start, end+1):
        stripped = lines[i].strip()
        if stripped.startswith('!'):
            continue
        code = strip_comment(stripped).lower().strip()

        # Match allocate( but not deallocate(
        if re.match(r'^allocate\s*\(', code) and 'stat=' not in code:
            result.append(i)
    return result


def find_allocate_end(lines, start_line, max_line):
    """Find the last line of a multi-line allocate statement."""
    paren_count = 0
    for i in range(start_line, max_line+1):
        line = lines[i]
        stripped = strip_comment(line.strip())
        for ch in stripped:
            if ch == '(':
                paren_count += 1
            elif ch == ')':
                paren_count -= 1
                if paren_count == 0:
                    return i
    return start_line  # fallback


def add_stat_ierr(line):
    """Add ,stat=ierr before the last closing paren of an allocate line."""
    rline = line.rstrip('\n').rstrip()
    # Find the last ')' that completes the allocate
    last_paren = rline.rfind(')')
    if last_paren == -1:
        return line
    new_line = rline[:last_paren] + ',stat=ierr' + rline[last_paren:]
    if line.endswith('\n'):
        new_line += '\n'
    return new_line


def get_indent(line):
    """Get the leading whitespace of a line."""
    match = re.match(r'^(\s*)', line)
    return match.group(1) if match else ''


def process_file(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()

    routines = find_routines(lines)

    # For each routine, gather info
    changes = []  # list of dicts with action info

    for rstart, rname, rend in routines:
        alloc_lines = find_allocate_lines(lines, rstart, rend)
        if not alloc_lines:
            continue

        has_ierr = has_ierr_decl(lines, rstart, rend)
        decl_end = find_declaration_end(lines, rstart, rend)

        changes.append({
            'name': rname,
            'start': rstart,
            'end': rend,
            'alloc_lines': alloc_lines,
            'has_ierr': has_ierr,
            'decl_end': decl_end
        })

    # Collect all modifications
    modifications = {}  # line_num -> new line content
    insertions = {}     # line_num -> list of lines to insert AFTER

    for ch in changes:
        # Add ierr declaration if needed
        if not ch['has_ierr']:
            decl_line = ch['decl_end']
            if decl_line is not None:
                indent = get_indent(lines[decl_line])
                ierr_line = indent + 'integer ierr\n'
                if decl_line not in insertions:
                    insertions[decl_line] = []
                insertions[decl_line].append(ierr_line)
            else:
                print(f"  WARNING: could not find declaration section in {ch['name']} (line {ch['start']+1})")

        # Process allocate calls
        for alloc_start in ch['alloc_lines']:
            alloc_end = find_allocate_end(lines, alloc_start, ch['end'])

            # Add stat=ierr to the line with the closing paren
            modifications[alloc_end] = add_stat_ierr(lines[alloc_end])

            # Add error check after
            indent = get_indent(lines[alloc_start])
            check_line = indent + "if( ierr /= 0 ) stop 'error stop: allocation failed'\n"
            if alloc_end not in insertions:
                insertions[alloc_end] = []
            insertions[alloc_end].append(check_line)

    # Rebuild file
    new_lines = []
    for i, line in enumerate(lines):
        if i in modifications:
            new_lines.append(modifications[i])
        else:
            new_lines.append(line)

        if i in insertions:
            for ins in insertions[i]:
                new_lines.append(ins)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)

    n_alloc = sum(len(ch['alloc_lines']) for ch in changes)
    n_ierr = sum(1 for ch in changes if not ch['has_ierr'])
    print(f"  {filepath}:")
    print(f"    {n_alloc} allocate calls modified")
    print(f"    {n_ierr} ierr declarations added")
    for ch in changes:
        print(f"    routine {ch['name']}: {len(ch['alloc_lines'])} allocates, has_ierr={ch['has_ierr']}, decl_end={ch['decl_end']}")

    return n_alloc


if __name__ == '__main__':
    files = [
        '/home/razinka/shyfem/src/utils/shympi/mpi_node.f90',
        '/home/razinka/shyfem/src/utils/shympi/mpi_tvd.f90',
        '/home/razinka/shyfem/src/utils/shympi/mpi_dummy.f90',
        '/home/razinka/shyfem/src/utils/shympi/mpi_basin.f90',
        '/home/razinka/shyfem/src/utils/shympi/mpi_node_internal.f90',
    ]

    total = 0
    for f in files:
        print(f"\nProcessing {f}...")
        total += process_file(f)
    print(f"\nTotal: {total} allocate calls modified")
