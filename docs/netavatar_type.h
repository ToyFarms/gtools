//==============================================================================
// NetAvatar -- explicit byte-exact layout (protocol 226 / game_version 5.58)
//
// Drop-in replacement for the padded IDB type. Every known field is spelled
// out; everything unmapped stays as an explicitly sized `unk_XXXX` reserve so
// the offsets never shift. All offsets verified against the IDB disassembly
// and the map in docs/netavatar-physics.md.
//
// Requires the existing local type:
//     struct NetAvatarAxis { float half; int flags; float value; float base; };
//
// Usage: Local Types -> delete the old NetAvatar, paste this file.
//
// Notes:
//  * The known layout ends at 0x2DB8 (the physics allocation size of
//    operator new(0x2DB8) @ 0x140402019). The old IDB type ran to 0x6288; a
//    commented tail is at the bottom if you want to keep that size.
//  * `0x10`/`0x14` are the collision rect width/height (getPlayerCollisionRect
//    @ 0x140512630); `0x08`/`0x0C` are its top-left.
//  * Axis triplets are NetAvatarAxis (half @ +0, flags @ +4, value @ +8, base @ +0xC).
//  * Named `unk_XXXX` reserves are still unmapped, but their sizes are exact;
//    rename them as more of the struct is reversed.
//  * A few extents are inferred from the next known offset rather than from a
//    verified end marker: clothes_358, effect_3B8, tileCache_2E0, the slot_2XX
//    words. Adjust them if a narrower field turns up.
//==============================================================================

#pragma pack(push, 1)
struct NetAvatar
{
    void       *vftable;                  // 0x000
    float       posx;                     // 0x008  collision-rect left
    float       posy;                     // 0x00C  collision-rect top
    float       collisionWidth;           // 0x010  used by getPlayerCollisionRect / tile queries
    float       collisionHeight;          // 0x014
    _DWORD      unk_018;                  // 0x018
    float       velx;                     // 0x01C  network/render velocity
    float       vely;                     // 0x020
    _BYTE       unk_024[0x1C];            // 0x024
    _BYTE       unk_040[0x0C];            // 0x040
    _BYTE       flag_4C;                  // 0x04C  tickAux early-out when non-zero
    _BYTE       unk_04D[0x13];            // 0x04D
    _BYTE       inWorld;                  // 0x060  sub_140512960 only queries when set
    _BYTE       facingLeft;               // 0x061  seed for the Y damaging response, FACING_LEFT
    _BYTE       unk_062[2];               // 0x062
    float       fracx;                    // 0x064  moveByPixels sub-pixel remainder
    float       fracy;                    // 0x068
    _DWORD      unk_06C;                  // 0x06C
    _DWORD      unk_070;                  // 0x070  zeroed by onPositionSnapped
    _DWORD      unk_074;                  // 0x074
    float       timer_078;                // 0x078  tickAux countdown
    _DWORD      waterEnterMs;             // 0x07C  getTick() when the avatar entered water
    NetAvatarAxis axis80;                 // 0x080  triplet, C = 0
    _BYTE       unk_090[0x38];            // 0x090
    float       jumpCharge;               // 0x0C8  charged-jump timer (modBit0), 0..1
    _DWORD      counter_0CC;              // 0x0CC  zeroed by the tile-below query and the climb grab
    int         bounceTileX;              // 0x0D0  onTileBounceHit (0x140502AB0)
    int         bounceTileY;              // 0x0D4
    int         peak_0D8;                 // 0x0D8  0xD8 = max(0xD8, 0xCC) in sub_140505CB0
    _BYTE       onGround;                 // 0x0DC  flag_DC
    _BYTE       slideFlag;                // 0x0DD  0xDD, TANKFLAG_SLIDE
    _BYTE       mudFlag;                  // 0x0DE  0xDE, cap *= 0.6 and the reduced jump
    _BYTE       parasolFlag_0DF;          // 0x0DF  slow-fall group A -> TANKFLAG_PARASOL
    _BYTE       glideFlag_0E0;            // 0x0E0  slow-fall group B -> TANKFLAG_UNK_GRAVITY_RELATED
    _BYTE       doubleJumpAnim;           // 0x0E1  0xE1, STATE flag bit 26
    _BYTE       unk_0E2[2];               // 0x0E2
    NetAvatarAxis horizontalVelocity;     // 0x0E4  C = 0
    NetAvatarAxis verticalVelocity;       // 0x0F4  C = 0
    _BYTE       axisValid;                // 0x104
    _BYTE       jumpHeld;                 // 0x105  setJumpHeld
    _BYTE       unk_106[6];               // 0x106
    _DWORD      timerFlag_10C;            // 0x10C  tickAux gate
    float       timer_110;                // 0x110  tickAux countdown
    _BYTE       unk_114[0xC];             // 0x114
    void       *pendingStateBlock;        // 0x120  pending server STATE snapshot (checked by onBurn and friends)
    void       *renderObj_128;            // 0x128  byte +140/+142 set by the snapshot path
    _BYTE       jumpLatch;                // 0x130  0x130, gates the +5000 jump cut
    _BYTE       damageSlip;               // 0x131  0x131, set by the Y damaging response, cleared on ground contact
    _BYTE       unk_132[2];               // 0x132
    _DWORD      eventMask_134;            // 0x134  transient one-shot event bits (FIRE_DAMAGE, GOT_KILLED, ...)
    _DWORD      specialState_138;         // 0x138  dying latch (2 while dead)
    _DWORD      itemId_13C;               // 0x13C  item id passed to CanPassThroughTile / tile queries
    _BYTE       leftGround_140;           // 0x140  set when the ground query fails after being grounded
    _BYTE       unk_141[0x17];            // 0x141
    _DWORD      antigravity_158;          // 0x158  field_158, gravity overrides
    _BYTE       unk_15C[0x20];            // 0x15C
    _DWORD      bounceItemId;             // 0x17C  item id written by onTileBounceHit
    _BYTE       unk_180[8];               // 0x180
    _DWORD      charFlags_188;            // 0x188  CharacterFlags (NOCLIP 1, FROZEN 0x800, IGNORE_LAVA 0x200, IGNORE_SPIKES 0x400, ...)
    _DWORD      inputFlags_18C;           // 0x18C  inverted controls 0x800, Will-of-the-Wild toggle 0x100
    _BYTE       unk_190[0x10];            // 0x190
    _BYTE       waterInput;               // 0x1A0  action 500005
    _BYTE       waterFlag;                // 0x1A1  TileFlags.IS_WET at the rect centre
    _BYTE       flag_1A2;                 // 0x1A2  sendTankState early-out together with 0x138
    _BYTE       unk_1A3[5];               // 0x1A3
    _BYTE       mods;                     // 0x1A8  SetCharacterMods
    _BYTE       modBit0;                  // 0x1A9  disables the jump cut
    _BYTE       modBit1;                  // 0x1AA
    _BYTE       unk_1AB[5];               // 0x1AB
    _BYTE       modBit2;                  // 0x1B0
    _BYTE       flag_1B1;                 // 0x1B1  set when 0x1B0 is non-zero
    _BYTE       accelMulFlag;             // 0x1B2  accel *= 15 when set
    _BYTE       unk_1B3[9];               // 0x1B3
    _BYTE       inputFlag_1BC;            // 0x1BC  action 500006
    _BYTE       inputFlag_1BD;            // 0x1BD  action 500007
    _BYTE       unk_1BE[6];               // 0x1BE
    NetAvatarAxis verticalAcceleration;   // 0x1C4  C = 1000
    NetAvatarAxis horizontalMoveSpeed;    // 0x1D4  C = 1200
    NetAvatarAxis gravity;                // 0x1E4  C = 250 (horizontal speed cap)
    float       velocityInWater;          // 0x1F4  plain float, 125
    _BYTE       doubleJumpToken;          // 0x1F8  refilled while grounded with DOUBLE_JUMP, consumed by an air launch
    _BYTE       unk_1F9[3];               // 0x1F9
    NetAvatarAxis jumpStrength;           // 0x1FC  C = 0 initially, SET_CHARACTER_STATE vector_y
    _BYTE       unk_20C[0x24];            // 0x20C
    _BYTE       unk_230[0x30];            // 0x230  extra axis triplets reset by sub_14050B830
    _BYTE       unk_260[0x1C];            // 0x260
    int         tileIndex_27C;            // 0x27C  getTileAtPlayerPosition result index, -2 when none
    int         integrityCode_280;        // 0x280  last sendAppIntegrityFail code
    _BYTE       unk_284[0x18];            // 0x284
    _DWORD      counter_29C;              // 0x29C  decremented per tick in sub_140505CB0
    _DWORD      counter_2A0;              // 0x2A0  decremented while airborne
    _BYTE       unk_2A4[0x22];            // 0x2A4
    ItemID      clothingHat;              // 0x2C6  slow-fall group B / boot list (Celestial Halo, Zephyr Helm, Turkey Hat)
    _WORD       unk_2C8;                  // 0x2C8
    ItemID      clothingPants;            // 0x2CA  Super Squirt Gun Jetpack Pants
    ItemID      clothingShoes;            // 0x2CC  slow-fall/water/boot checks
    _WORD       unk_2CE;                  // 0x2CE  checked via sub_14053BE70
    ItemID      clothingHand;             // 0x2D0  parasols, water wings, ...
    ItemID      clothingBack;             // 0x2D2  wings, jetpacks, cloaks
    ItemID      clothingHair;             // 0x2D4  Rayman's Hair
    ItemID      clothingNeck;             // 0x2D6  scarves, floaties
    _BYTE       unk_2D8[8];               // 0x2D8
    _QWORD      tileCache_2E0;            // 0x2E0  passed to TileExistsAt (0x140519D80) for the rope-piton check
    _BYTE       unk_2E8[0x70];            // 0x2E8
    _BYTE       clothes_358[0x60];        // 0x358  embedded Clothes object, first arg of getClothes (extent inferred)
    _BYTE       effect_3B8[0x1BD4];       // 0x3B8  embedded avatar effect/audio object (sub_140131EA0, sub_140113DC0)
    float       trampolineMomentum;       // 0x1F8C read by the TRAMPOLINE_MOMENTUM (108) branch of vfunc_48
    _BYTE       unk_1F90[0x20];           // 0x1F90
    _BYTE       flag_1FB0;                // 0x1FB0 standing flag; clears the water float state
    _BYTE       unk_1FB1[8];              // 0x1FB1
    _BYTE       waterFloatFlag;           // 0x1FB9 water vehicle: gravity/fall = 0 for 3000 ms
    _BYTE       unk_1FBA[0x5E];           // 0x1FBA
    _BYTE       burnFlag_2018;            // 0x2018 gate before spawning the burn particles
    _BYTE       unk_2019[0x6F];           // 0x2019
    _BYTE       state_2088;               // 0x2088 set to 2 by the snapshot path (sub_140501290)
    _BYTE       unk_2089[0x5F];           // 0x2089
    _BYTE       burnState_20E8;           // 0x20E8 burn effect state (3 while burning)
    _BYTE       unk_20E9[0x4B];           // 0x20E9
    _DWORD      burnParam_2134;           // 0x2134 burn effect kind (0 = burn, 1 = acid/ouch)
    _DWORD      burnParam_2138;           // 0x2138
    _BYTE       unk_213C[0x58];           // 0x213C
    _DWORD      burnTimer_2194;           // 0x2194 now + 400 ms
    _DWORD      burnTimer_2198;           // 0x2198
    _BYTE       unk_219C[0x434];          // 0x219C
    float       speedCapMirror;           // 0x25D0 validatePhysics mirrors the computed cap here
    _BYTE       unk_25D4[0x6E0];          // 0x25D4
    _DWORD      unk_2CB4;                 // 0x2CB4
    _BYTE       unk_2CB8[8];              // 0x2CB8
    _QWORD      unk_2CC0;                 // 0x2CC0 ctor qword
    _BYTE       unk_2CC8[8];              // 0x2CC8
    _QWORD      unk_2CD0;                 // 0x2CD0 ctor qword
    _BYTE       trampolineMomentumArmed;  // 0x2CD8 set to 1 in the 108 branch
    _BYTE       unk_2CD9[3];              // 0x2CD9
    float       trampolineMomentumSquared;// 0x2CDC (0x1F8C / 400)^2
    NetAvatarAxis petAxis[6];             // 0x2CE0 petAxis0..5, 0x2CE0..0x2D3F
    _DWORD      unk_2D40;                 // 0x2D40 ctor writes 0
    _BYTE       unk_2D44;                 // 0x2D44 ctor writes byte 0
    _BYTE       unk_2D45[3];              // 0x2D45
    _DWORD      unk_2D48;                 // 0x2D48 ctor writes 6
    _BYTE       unk_2D4C[0x64];           // 0x2D4C
    _BYTE       unk_2DB0;                 // 0x2DB0 ctor writes 0
    _BYTE       unk_2DB1[7];              // 0x2DB1  -> end of the 0x2DB8 allocation
};
#pragma pack(pop)

// The old IDB type continued to 0x6288. Uncomment to keep that size:
// #pragma pack(push, 1)
// struct NetAvatarTail { _BYTE unk_2DB8[0x34D0]; };
// #pragma pack(pop)
