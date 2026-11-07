#include <idc.idc>

/*
 * export_ida_types.idc - write the current local type library as a C header.
 *
 * IDA Free has no IDAPython, but it supports IDC scripts:
 *     File -> Script file...    and select this file
 * or  File -> Script command...  (language: IDC, paste this body)
 *
 * Output: C:\Users\andra\ida_export\types.h
 *
 * Unlike the full-database IDC dump, this never walks the database (that
 * dump's Functions() section hits a corrupt record and aborts on this DB).
 * It only reads the type library and writes one header, so it is quick.
 */

static outfile()
{
    return "C:\\Users\\andra\\ida_export\\types.h";
}

static main()
{
    auto fh, i, limit, ordinals, text;

    fh = fopen(outfile(), "w");
    if (fh == 0)
    {
        warning("cannot create %s", outfile());
        return;
    }

    limit = get_ordinal_limit();
    ordinals = "";
    for (i = 1; i < limit; i = i + 1)
    {
        if (i > 1)
            ordinals = ordinals + ",";
        ordinals = ordinals + sprintf("%d", i);
    }

    msg("exporting %d local types...\n", limit - 1);
    text = print_decls(ordinals,
                       PDF_INCL_DEPS | PDF_DEF_FWD | PDF_DEF_BASE | PDF_HEADER_CMT);
    if (text == 0 || strlen(text) == 0)
    {
        warning("print_decls returned nothing");
        fclose(fh);
        return;
    }
    fprintf(fh, "%s\n", text);
    fclose(fh);
    msg("types written to %s (%d types)\n", outfile(), limit - 1);
}
