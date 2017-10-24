from ....address_translator import AT
from ....errors import CLEOperationError
from .elfreloc import ELFReloc
from ... import Symbol

import struct

import logging
l = logging.getLogger('cle.backends.elf.relocation.generic')

class GenericTLSDoffsetReloc(ELFReloc):
    @property
    def value(self):
        return self.addend + self.symbol.relative_addr

    def resolve_symbol(self, solist, bypass_compatibility=False):   # pylint: disable=unused-argument
        self.resolve(None)
        return True

class GenericTLSOffsetReloc(ELFReloc):
    def relocate(self, solist, bypass_compatibility=False):
        hell_offset = self.owner_obj.arch.elf_tls.tp_offset
        if self.symbol.type == Symbol.TYPE_NONE:
            self.owner_obj.memory.write_addr_at(
                self.relative_addr,
                self.owner_obj.tls_block_offset + self.addend + self.symbol.relative_addr - hell_offset)
            self.resolve(None)
        else:
            if not self.resolve_symbol(solist, bypass_compatibility):
                return False
            self.owner_obj.memory.write_addr_at(
                self.relative_addr,
                self.resolvedby.owner_obj.tls_block_offset + self.addend + self.symbol.relative_addr - hell_offset)
        return True

class GenericTLSModIdReloc(ELFReloc):
    def relocate(self, solist, bypass_compatibility=False):
        if self.symbol.type == Symbol.TYPE_NONE:
            self.owner_obj.memory.write_addr_at(self.relative_addr, self.owner_obj.tls_module_id)
            self.resolve(None)
        else:
            if not self.resolve_symbol(solist):
                return False
            self.owner_obj.memory.write_addr_at(self.relative_addr, self.resolvedby.owner_obj.tls_module_id)
        return True

class GenericIRelativeReloc(ELFReloc):
    def relocate(self, solist, bypass_compatibility=False):
        if self.symbol.type == Symbol.TYPE_NONE:
            self.owner_obj.irelatives.append((AT.from_lva(self.addend, self.owner_obj).to_mva(), self.relative_addr))
            self.resolve(None)
            return True

        if not self.resolve_symbol(solist, bypass_compatibility):
            return False

        self.owner_obj.irelatives.append((self.resolvedby.mapped_base, self.relative_addr))

class GenericAbsoluteAddendReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr + self.addend

class GenericPCRelativeAddendReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr + self.addend - self.rebased_addr

class GenericJumpslotReloc(ELFReloc):
    @property
    def value(self):
        if self.is_rela:
            return self.resolvedby.rebased_addr + self.addend
        else:
            return self.resolvedby.rebased_addr

class GenericRelativeReloc(ELFReloc):
    @property
    def value(self):
        return self.owner_obj.mapped_base + self.addend

    def resolve_symbol(self, solist, bypass_compatibility=False):
        self.resolve(None)
        return True

class GenericAbsoluteReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr

class GenericCopyReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.owner_obj.memory.read_addr_at(self.resolvedby.relative_addr)

class MipsGlobalReloc(GenericAbsoluteReloc):
    pass

class MipsLocalReloc(ELFReloc):
    def relocate(self, solist, bypass_compatibility=False): # pylint: disable=unused-argument
        if self.owner_obj.mapped_base == 0:
            self.resolve(None)
            return True                     # don't touch local relocations on the main bin
        delta = self.owner_obj.mapped_base - self.owner_obj._dynamic['DT_MIPS_BASE_ADDRESS']
        if delta == 0:
            self.resolve(None)
            return True
        val = self.owner_obj.memory.read_addr_at(self.relative_addr)
        newval = val + delta
        self.owner_obj.memory.write_addr_at(self.relative_addr, newval)
        self.resolve(None)
        return True

class RelocTruncate32Mixin(object):
    """
    A mix-in class for relocations that cover a 32-bit field regardless of the architecture's address word length.
    """

    # If True, 32-bit truncated value must equal to its original when zero-extended
    check_zero_extend = False

    # If True, 32-bit truncated value must equal to its original when sign-extended
    check_sign_extend = False

    def relocate(self, solist, bypass_compatibility=False): # pylint: disable=unused-argument
        if not self.resolve_symbol(solist):
            return False

        arch_bits = self.owner_obj.arch.bits
        assert arch_bits >= 32            # 16-bit makes no sense here

        val = self.value % (2**arch_bits)   # we must truncate it to native range first

        if (self.check_zero_extend and val >> 32 != 0 or
                self.check_sign_extend and val >> 32 != ((1 << (arch_bits - 32)) - 1)
                                                        if ((val >> 31) & 1) == 1 else 0):
            raise CLEOperationError("relocation truncated to fit: %s; consider making"
                                    " relevant addresses fit in the 32-bit address space." % self.__class__.__name__)

        by = struct.pack(self.owner_obj.arch.struct_fmt(32), val % (2**32))
        self.owner_obj.memory.write_bytes(self.dest_addr, by)
