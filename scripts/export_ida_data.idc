#include <idc.idc>

/*
 * export_ida_data.idc - dump IDA data/type information without Python.
 *
 * IDA Free has no IDAPython, but it does support IDC scripts:
 *     File -> Script file...    and select this file
 * or  File -> Script command...  (language: IDC) and paste this body
 *
 * Output directory: C:\Users\andra\ida_export
 *
 *     segments.tsv        segment table (name/start/end/size/perm/bitness)
 *     items.tsv           every item head: addr, size, code flag, segment,
 *                         name, type, comments, string value, hex preview
 *
 * The local type library is exported separately by export_ida_types.idc
 * (it uses IDA's print_decls() and never walks the database).
 *
 * NOTE: the built-in full dump gen_file(OFILE_IDC, ...) is intentionally not
 * used here: on this database its Functions() section hits a corrupt record
 * around 0x14040DC30 and IDA pops "The database is corrupted, some
 * information will not be saved", aborting the script.  The data sections of
 * that dump (LocalTypes/Bytes) complete, but the TSVs above are sufficient.
 *
 * The script is read-only: it never modifies the database.
 */

static outdir()
{
    return "C:\\Users\\andra\\ida_export";
}

// Escape tabs/newlines/backslashes/quotes so a field stays one TSV line.
static sanitize(s)
{
    auto i, n, ch, out;
    if (s == 0)
        return "";
    n = strlen(s);
    if (n == 0)
        return "";
    if (strstr(s, "\t") == -1 && strstr(s, "\n") == -1 &&
        strstr(s, "\r") == -1 && strstr(s, "\\") == -1 &&
        strstr(s, "\"") == -1)
        return s;
    out = "";
    for (i = 0; i < n; i = i + 1)
    {
        ch = substr(s, i, i + 1);
        if (ch == "\t")
            out = out + "\\t";
        else if (ch == "\n")
            out = out + "\\n";
        else if (ch == "\r")
            out = out + "\\r";
        else if (ch == "\\")
            out = out + "\\\\";
        else if (ch == "\"")
            out = out + "\\\"";
        else
            out = out + ch;
    }
    return out;
}

static dump_segments(fh)
{
    auto seg, s, e;
    fprintf(fh, "name\tstart\tend\tsize\tperm\tbitness\n");
    seg = get_first_seg();
    while (seg != BADADDR)
    {
        s = get_segm_attr(seg, SEGATTR_START);
        e = get_segm_attr(seg, SEGATTR_END);
        fprintf(fh, "%s\t0x%X\t0x%X\t%d\t%d\t%d\n",
                sanitize(get_segm_name(seg)), s, e, e - s,
                get_segm_attr(seg, SEGATTR_PERM),
                get_segm_attr(seg, SEGATTR_BITNESS));
        seg = get_next_seg(seg);
    }
}

static dump_items(fh)
{
    auto seg, segname, s, e, ea, nxt, f, sz, code;
    auto nm, ty, cm, rc, strv, hexv, i, m;

    fprintf(fh, "addr\tsize\tcode\tsegment\tname\ttype\tcomment\trcomment\tstring\thex\n");
    seg = get_first_seg();
    while (seg != BADADDR)
    {
        s = get_segm_attr(seg, SEGATTR_START);
        e = get_segm_attr(seg, SEGATTR_END);
        segname = sanitize(get_segm_name(seg));
        ea = s;
        while (ea < e)
        {
            f = get_full_flags(ea);
            if (is_head(f))
            {
                sz = get_item_size(ea);
                if (sz > 0)
                {
                    code = is_code(f);
                    nm = sanitize(get_name(ea));
                    ty = sanitize(get_type(ea));
                    cm = sanitize(get_cmt(ea, 0));
                    rc = sanitize(get_cmt(ea, 1));
                    strv = "";
                    hexv = "";
                    if (is_strlit(f))
                        strv = sanitize(get_strlit_contents(ea, -1, get_str_type(ea)));
                    if (is_data(f))
                    {
                        m = sz;
                        if (m > 16)
                            m = 16;
                        for (i = 0; i < m; i = i + 1)
                            hexv = hexv + sprintf("%02X", Byte(ea + i));
                    }
                    fprintf(fh, "0x%X\t%d\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n",
                            ea, sz, code, segname, nm, ty, cm, rc, strv, hexv);
                }
            }
            nxt = next_head(ea, e);
            if (nxt == BADADDR || nxt <= ea)
                break;
            ea = nxt;
        }
        seg = get_next_seg(seg);
    }
}

static main()
{
    auto d, fh;

    d = outdir();
    msg("export: starting -> %s\n", d);

    fh = fopen(d + "\\segments.tsv", "w");
    if (fh != 0)
    {
        dump_segments(fh);
        fclose(fh);
        msg("export: segments.tsv done\n");
    }
    else
        warning("export: cannot create segments.tsv");

    fh = fopen(d + "\\items.tsv", "w");
    if (fh != 0)
    {
        dump_items(fh);
        fclose(fh);
        msg("export: items.tsv done\n");
    }
    else
        warning("export: cannot create items.tsv");

    msg("export: finished -> %s\n", d);
}
