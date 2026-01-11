// this function returns an index, presumably a texture index, based on the connectivity of the 8 neighboring tiles
__int64 __fastcall determineAutoTileIndexFromNeighbor(WorldView *worldView, Tile *tile, int a3)
{
  int tileX; // r15d
  unsigned int v4; // ebp
  int tileY; // r12d
  int width; // r8d
  int v9; // esi
  int bg; // edx
  Tile *v11; // rax
  ItemID v12; // cx
  bool v13; // zf
  char v14; // r11
  int v15; // r10d
  Tile *v16; // rax
  ItemID v17; // cx
  bool v18; // zf
  bool v19; // al
  Tile *v20; // rcx
  ItemID v21; // r9
  bool v22; // zf
  bool v23; // al
  int v24; // r9d
  Tile *v25; // rcx
  ItemID v26; // r10
  bool v27; // zf
  char SouthWestTile; // r14
  Tile *v29; // rcx
  ItemID v30; // r10
  bool v31; // zf
  char WestTile; // r12
  int v33; // ecx
  Tile *v34; // r9
  ItemID v35; // r10
  bool v36; // zf
  char NorthWestTile; // di
  Tile *v38; // r9
  ItemID v39; // r10
  char NorthTile; // r15
  Tile *v41; // rax
  ItemID v42; // cx
  bool v43; // zf
  char SouthEastTile_1; // cl
  char NorthEastTile; // al
  char SouthTile_1; // dl
  int v47; // eax
  int tileX_Plus_One; // esi
  ItemID ForegroundOrBackgroundId; // ax
  ItemID v50; // ax
  ItemID v51; // ax
  ItemID v52; // ax
  ItemID v53; // ax
  ItemID v54; // ax
  ItemID v55; // ax
  ItemID v56; // ax
  unsigned int v57; // esi
  unsigned int v59; // ebp
  unsigned int v60; // ebp
  unsigned int v61; // ebp
  unsigned int v62; // ebp
  unsigned int v63; // ebp
  unsigned int v64; // ebp
  bool EastTile_1; // [rsp+30h] [rbp-48h]
  char EastTile; // [rsp+30h] [rbp-48h]
  int tileY_1; // [rsp+34h] [rbp-44h]
  int v68; // [rsp+38h] [rbp-40h]
  bool v70; // [rsp+90h] [rbp+18h]
  bool SouthEastTile; // [rsp+90h] [rbp+18h]
  char v72; // [rsp+90h] [rbp+18h]
  char v73; // [rsp+98h] [rbp+20h]
  bool SouthTile; // [rsp+98h] [rbp+20h]
  char v75; // [rsp+98h] [rbp+20h]

  tileX = (unsigned __int8)tile->tileX;
  v4 = 0;
  tileY = (unsigned __int8)tile->tileY;
  v68 = tileX;
  tileY_1 = tileY;
  if ( a3 == 1 )
  {
    width = worldView->width;
    v9 = tileX + 1;
    bg = tile->bg;
    if ( tileX + 1 >= width )
      goto LABEL_10;
    if ( tileY >= worldView->height )
      goto LABEL_10;
    v11 = &worldView->tilesBegin[tileX + 1 + tileY * width];
    if ( !v11 )
      goto LABEL_10;
    v12 = v11->bg;
    if ( v12 )
    {
      if ( (v11->flags & GLUED) != 0 )
        goto LABEL_10;
    }
    if ( bg == 8930 )
    {
      v13 = v12 == WEEPING_WILLOW;
    }
    else
    {
      if ( bg != 1194 )
      {
        if ( bg == 3556 && v12 == DWARVEN_BACKGROUND )
          goto LABEL_10;
        goto LABEL_30;
      }
      v13 = v12 == TWISTED_WINDOWS;
    }
    if ( v13 )
    {
LABEL_10:
      v14 = 1;
LABEL_11:
      v15 = tileY + 1;
      if ( v9 >= width )
        goto LABEL_19;
      if ( v15 >= worldView->height )
        goto LABEL_19;
      v16 = &worldView->tilesBegin[tileX + 1 + v15 * width];
      if ( !v16 )
        goto LABEL_19;
      v17 = v16->bg;
      if ( v17 )
      {
        if ( (v16->flags & 0x800) != 0 )
          goto LABEL_19;
      }
      if ( bg == 8930 )
      {
        v18 = v17 == WEEPING_WILLOW;
      }
      else
      {
        if ( bg != 1194 )
        {
          if ( bg == 3556 && v17 == DWARVEN_BACKGROUND )
            goto LABEL_19;
          goto LABEL_35;
        }
        v18 = v17 == TWISTED_WINDOWS;
      }
      if ( v18 )
      {
LABEL_19:
        v19 = 1;
LABEL_20:
        v70 = v19;
        if ( tileX >= width )
          goto LABEL_39;
        if ( v15 >= worldView->height )
          goto LABEL_39;
        v20 = &worldView->tilesBegin[tileX + v15 * width];
        if ( !v20 )
          goto LABEL_39;
        v21 = v20->bg;
        if ( v21 && (v20->flags & 0x800) != 0 )
        {
          v73 = 1;
LABEL_41:
          v24 = tileX - 1;
          if ( tileX - 1 < 0 )
            goto LABEL_50;
          if ( v24 >= width )
            goto LABEL_50;
          if ( v15 >= worldView->height )
            goto LABEL_50;
          v25 = &worldView->tilesBegin[v24 + v15 * width];
          if ( !v25 )
            goto LABEL_50;
          v26 = v25->bg;
          if ( v26 )
          {
            if ( (v25->flags & 0x800) != 0 )
              goto LABEL_50;
          }
          if ( bg == 8930 )
          {
            v27 = v26 == WEEPING_WILLOW;
          }
          else
          {
            if ( bg != 1194 )
            {
              if ( bg == 3556 && v26 == DWARVEN_BACKGROUND )
                goto LABEL_50;
              goto LABEL_90;
            }
            v27 = v26 == TWISTED_WINDOWS;
          }
          if ( v27 )
          {
LABEL_50:
            SouthWestTile = 1;
LABEL_51:
            if ( v24 < 0 )
              goto LABEL_60;
            if ( v24 >= width )
              goto LABEL_60;
            if ( tileY >= worldView->height )
              goto LABEL_60;
            v29 = &worldView->tilesBegin[v24 + tileY * width];
            if ( !v29 )
              goto LABEL_60;
            v30 = v29->bg;
            if ( v30 )
            {
              if ( (v29->flags & 0x800) != 0 )
                goto LABEL_60;
            }
            if ( bg == 8930 )
            {
              v31 = v30 == WEEPING_WILLOW;
            }
            else
            {
              if ( bg != 1194 )
              {
                if ( bg == 3556 && v30 == DWARVEN_BACKGROUND )
                  goto LABEL_60;
                goto LABEL_95;
              }
              v31 = v30 == TWISTED_WINDOWS;
            }
            if ( v31 )
            {
LABEL_60:
              WestTile = 1;
LABEL_61:
              v33 = tileY_1 - 1;
              if ( v24 < 0 )
                goto LABEL_71;
              if ( v33 < 0 )
                goto LABEL_71;
              if ( v24 >= width )
                goto LABEL_71;
              if ( v33 >= worldView->height )
                goto LABEL_71;
              v34 = &worldView->tilesBegin[v24 + v33 * width];
              if ( !v34 )
                goto LABEL_71;
              v35 = v34->bg;
              if ( v35 )
              {
                if ( (v34->flags & 0x800) != 0 )
                  goto LABEL_71;
              }
              if ( bg == 8930 )
              {
                v36 = v35 == WEEPING_WILLOW;
              }
              else
              {
                if ( bg != 1194 )
                {
                  if ( bg == 3556 && v35 == DWARVEN_BACKGROUND )
                    goto LABEL_71;
                  goto LABEL_100;
                }
                v36 = v35 == TWISTED_WINDOWS;
              }
              if ( v36 )
              {
LABEL_71:
                NorthWestTile = 1;
LABEL_72:
                if ( v33 < 0 )
                  goto LABEL_107;
                if ( tileX >= width )
                  goto LABEL_107;
                if ( v33 >= worldView->height )
                  goto LABEL_107;
                v38 = &worldView->tilesBegin[tileX + v33 * width];
                if ( !v38 )
                  goto LABEL_107;
                v39 = v38->bg;
                if ( v39 )
                {
                  if ( (v38->flags & 0x800) != 0 )
                    goto LABEL_107;
                }
                if ( bg == 8930 )
                {
                  if ( v39 == WEEPING_WILLOW )
                  {
LABEL_107:
                    NorthTile = 1;
                    goto LABEL_108;
                  }
                }
                else if ( bg == 1194 )
                {
                  if ( v39 == TWISTED_WINDOWS )
                    goto LABEL_107;
                }
                else if ( bg == 3556 && v39 == DWARVEN_BACKGROUND )
                {
                  goto LABEL_107;
                }
                NorthTile = (unsigned __int16)v39 == bg;
LABEL_108:
                if ( v33 < 0 )
                  goto LABEL_117;
                if ( v9 >= width )
                  goto LABEL_117;
                if ( v33 >= worldView->height )
                  goto LABEL_117;
                v41 = &worldView->tilesBegin[width * v33 + 1 + v68];
                if ( !v41 )
                  goto LABEL_117;
                v42 = v41->bg;
                if ( v42 )
                {
                  if ( (v41->flags & 0x800) != 0 )
                    goto LABEL_117;
                }
                if ( bg == 8930 )
                {
                  v43 = v42 == WEEPING_WILLOW;
                }
                else
                {
                  if ( bg != 1194 )
                  {
                    if ( bg == 3556 && v42 == DWARVEN_BACKGROUND )
                      goto LABEL_117;
LABEL_122:
                    v47 = v42;
                    SouthEastTile_1 = v70;
                    v13 = v47 == bg;
                    SouthTile_1 = v73;
                    NorthEastTile = v13;
                    goto LABEL_128;
                  }
                  v43 = v42 == TWISTED_WINDOWS;
                }
                if ( v43 )
                {
LABEL_117:
                  SouthEastTile_1 = v70;
                  NorthEastTile = 1;
                  SouthTile_1 = v73;
                  goto LABEL_128;
                }
                goto LABEL_122;
              }
LABEL_100:
              NorthWestTile = (unsigned __int16)v35 == bg;
              goto LABEL_72;
            }
LABEL_95:
            WestTile = (unsigned __int16)v30 == bg;
            goto LABEL_61;
          }
LABEL_90:
          SouthWestTile = (unsigned __int16)v26 == bg;
          goto LABEL_51;
        }
        if ( bg == 8930 )
        {
          v22 = v21 == WEEPING_WILLOW;
        }
        else
        {
          if ( bg != 1194 )
          {
            if ( bg == 3556 && v21 == DWARVEN_BACKGROUND )
              goto LABEL_39;
            goto LABEL_85;
          }
          v22 = v21 == TWISTED_WINDOWS;
        }
        if ( v22 )
        {
LABEL_39:
          v23 = 1;
LABEL_40:
          v73 = v23;
          goto LABEL_41;
        }
LABEL_85:
        v23 = (unsigned __int16)v21 == bg;
        goto LABEL_40;
      }
LABEL_35:
      v19 = (unsigned __int16)v17 == bg;
      goto LABEL_20;
    }
LABEL_30:
    v14 = (unsigned __int16)v12 == bg;
    goto LABEL_11;
  }
  if ( a3 )
  {
    if ( a3 == 2 )
    {
      v57 = tileX + 1;
      EastTile = sub_140565DF0(worldView, (unsigned int)(tileX + 1), (unsigned __int8)tile->tileY);
      v72 = sub_140565DF0(worldView, (unsigned int)(tileX + 1), (unsigned int)(tileY + 1));
      v75 = sub_140565DF0(worldView, (unsigned int)tileX, (unsigned int)(tileY + 1));
      SouthWestTile = sub_140565DF0(worldView, (unsigned int)(tileX - 1), (unsigned int)(tileY + 1));
      WestTile = sub_140565DF0(worldView, (unsigned int)(tileX - 1), (unsigned int)tileY);
      NorthWestTile = sub_140565DF0(worldView, (unsigned int)(tileX - 1), (unsigned int)(tileY_1 - 1));
      NorthTile = sub_140565DF0(worldView, (unsigned int)tileX, (unsigned int)(tileY_1 - 1));
      NorthEastTile = sub_140565DF0(worldView, v57, (unsigned int)(tileY_1 - 1));
      SouthEastTile_1 = v72;
      SouthTile_1 = v75;
      v14 = EastTile;
    }
    else
    {
      NorthEastTile = HIBYTE(tile);
      NorthTile = BYTE6(tile);
      NorthWestTile = BYTE5(tile);
      WestTile = BYTE4(tile);
      SouthWestTile = BYTE3(tile);
      SouthTile_1 = BYTE2(tile);
      SouthEastTile_1 = BYTE1(tile);
      v14 = (char)tile;
    }
  }
  else
  {
    tileX_Plus_One = tileX + 1;
    ForegroundOrBackgroundId = getForegroundOrBackgroundId(tile);
    EastTile_1 = checkIfTileIsConnected(worldView, tileX + 1, tileY, ForegroundOrBackgroundId, 0);
    v50 = getForegroundOrBackgroundId(tile);
    SouthEastTile = checkIfTileIsConnected(worldView, tileX + 1, tileY + 1, v50, 0);
    v51 = getForegroundOrBackgroundId(tile);
    SouthTile = checkIfTileIsConnected(worldView, tileX, tileY + 1, v51, 0);
    v52 = getForegroundOrBackgroundId(tile);
    SouthWestTile = checkIfTileIsConnected(worldView, tileX - 1, tileY + 1, v52, 0);
    v53 = getForegroundOrBackgroundId(tile);
    WestTile = checkIfTileIsConnected(worldView, tileX - 1, tileY, v53, 0);
    v54 = getForegroundOrBackgroundId(tile);
    NorthWestTile = checkIfTileIsConnected(worldView, tileX - 1, tileY_1 - 1, v54, 0);
    v55 = getForegroundOrBackgroundId(tile);
    NorthTile = checkIfTileIsConnected(worldView, tileX, tileY_1 - 1, v55, 0);
    v56 = getForegroundOrBackgroundId(tile);
    NorthEastTile = checkIfTileIsConnected(worldView, tileX_Plus_One, tileY_1 - 1, v56, 0);
    SouthEastTile_1 = SouthEastTile;
    SouthTile_1 = SouthTile;
    v14 = EastTile_1;
  }
LABEL_128:
  if ( !v14 )
    goto LABEL_195;
  if ( !SouthTile_1 )
  {
    if ( WestTile && NorthTile )
    {
      if ( NorthWestTile )
      {
        if ( NorthEastTile )
          return 2;
        else
          return 41;
      }
      else if ( NorthEastTile )
      {
        return 40;
      }
      else
      {
        return 42;
      }
    }
    goto LABEL_186;
  }
  if ( !WestTile )
  {
LABEL_186:
    if ( !SouthTile_1 )
    {
LABEL_205:
      if ( v14 )
      {
        if ( SouthTile_1 )
        {
          v61 = 45;
          if ( SouthEastTile_1 )
            return 5;
          return v61;
        }
        else if ( WestTile )
        {
          return 28;
        }
        else if ( NorthTile )
        {
          v62 = 43;
          if ( NorthEastTile )
            return 7;
          return v62;
        }
        else
        {
          return 29;
        }
      }
      else if ( SouthTile_1 )
      {
        if ( WestTile )
        {
          v63 = 46;
          if ( SouthWestTile )
            return 6;
          return v63;
        }
        else if ( NorthTile )
        {
          return 9;
        }
        else
        {
          return 10;
        }
      }
      else
      {
        if ( !WestTile )
          return 12 - (unsigned int)(NorthTile != 0);
        if ( NorthTile )
        {
          v64 = 44;
          if ( NorthWestTile )
            return 8;
          return v64;
        }
        else
        {
          return 30;
        }
      }
    }
    if ( NorthTile )
    {
      if ( NorthEastTile )
      {
        if ( SouthEastTile_1 )
          return 3;
        else
          return 32;
      }
      else if ( SouthEastTile_1 )
      {
        return 31;
      }
      else
      {
        return 33;
      }
    }
LABEL_195:
    if ( SouthTile_1 && WestTile && NorthTile )
    {
      if ( NorthWestTile )
      {
        if ( SouthWestTile )
          return 4;
        else
          return 35;
      }
      else if ( SouthWestTile )
      {
        return 34;
      }
      else
      {
        return 36;
      }
    }
    goto LABEL_205;
  }
  if ( NorthTile )
  {
    if ( SouthEastTile_1 )
    {
      if ( SouthWestTile )
      {
        if ( NorthWestTile )
        {
          if ( !NorthEastTile )
            return 14;
          return v4;
        }
        if ( NorthEastTile )
          return 13;
      }
      if ( NorthWestTile && NorthEastTile )
        return 15;
    }
    if ( SouthWestTile && NorthWestTile && NorthEastTile )
      return 16;
    if ( SouthEastTile_1 )
    {
      if ( SouthWestTile )
        return 17;
    }
    else if ( SouthWestTile )
    {
      if ( NorthWestTile )
        return 20;
LABEL_160:
      if ( SouthWestTile && NorthEastTile )
        return 21;
      if ( SouthEastTile_1 )
        return 26;
      if ( SouthWestTile )
        return 25;
      if ( NorthWestTile )
        return 23;
      v59 = 27;
      if ( NorthEastTile )
        return 24;
      return v59;
    }
    if ( NorthWestTile && NorthEastTile )
      return 18;
    if ( SouthEastTile_1 )
    {
      if ( NorthEastTile )
        return 19;
      if ( NorthWestTile )
        return 22;
    }
    goto LABEL_160;
  }
  if ( !SouthEastTile_1 )
    return 39 - (unsigned int)(SouthWestTile != 0);
  v60 = 37;
  if ( SouthWestTile )
    return 1;
  return v60;
}
