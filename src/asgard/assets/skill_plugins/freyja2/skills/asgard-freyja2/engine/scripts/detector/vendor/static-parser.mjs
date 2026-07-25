/**
 * Vendored static-HTML parser bundle for Freyja 2's detector.
 *
 * Bundles htmlparser2, css-select, css-tree and domutils — the four packages
 * `engines/static-html/detect-html.mjs` needs to build a real DOM and resolve
 * the CSS cascade. Upstream gets them as dependencies of its npm package;
 * Asgard ships this engine as Python package data with no node_modules beside
 * it, so every bare import threw and the detector fell back to regex-only,
 * losing the contrast, spacing and type-size rule sets with no warning.
 *
 * Generated — do not edit. Regenerate with ./rebuild.sh.
 * Upstream licenses are recorded in LICENSES.md beside this file.
 */
var __create = Object.create;
var __getProtoOf = Object.getPrototypeOf;
var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
function __accessProp(key) {
  return this[key];
}
var __toESMCache_node;
var __toESMCache_esm;
var __toESM = (mod, isNodeMode, target) => {
  var canCache = mod != null && typeof mod === "object";
  if (canCache) {
    var cache = isNodeMode ? __toESMCache_node ??= new WeakMap : __toESMCache_esm ??= new WeakMap;
    var cached = cache.get(mod);
    if (cached)
      return cached;
  }
  target = mod != null ? __create(__getProtoOf(mod)) : {};
  const to = isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target;
  for (let key of __getOwnPropNames(mod))
    if (!__hasOwnProp.call(to, key))
      __defProp(to, key, {
        get: __accessProp.bind(mod, key),
        enumerable: true
      });
  if (canCache)
    cache.set(mod, to);
  return to;
};
var __commonJS = (cb, mod) => () => (mod || cb((mod = { exports: {} }).exports, mod), mod.exports);
var __returnValue = (v) => v;
function __exportSetter(name, newValue) {
  this[name] = __returnValue.bind(null, newValue);
}
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, {
      get: all[name],
      enumerable: true,
      configurable: true,
      set: __exportSetter.bind(all, name)
    });
};

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/types.cjs
var require_types = __commonJS((exports) => {
  var EOF = 0;
  var Ident = 1;
  var Function = 2;
  var AtKeyword = 3;
  var Hash = 4;
  var String2 = 5;
  var BadString = 6;
  var Url = 7;
  var BadUrl = 8;
  var Delim = 9;
  var Number2 = 10;
  var Percentage = 11;
  var Dimension = 12;
  var WhiteSpace = 13;
  var CDO = 14;
  var CDC = 15;
  var Colon = 16;
  var Semicolon = 17;
  var Comma = 18;
  var LeftSquareBracket = 19;
  var RightSquareBracket = 20;
  var LeftParenthesis = 21;
  var RightParenthesis = 22;
  var LeftCurlyBracket = 23;
  var RightCurlyBracket = 24;
  var Comment3 = 25;
  exports.AtKeyword = AtKeyword;
  exports.BadString = BadString;
  exports.BadUrl = BadUrl;
  exports.CDC = CDC;
  exports.CDO = CDO;
  exports.Colon = Colon;
  exports.Comma = Comma;
  exports.Comment = Comment3;
  exports.Delim = Delim;
  exports.Dimension = Dimension;
  exports.EOF = EOF;
  exports.Function = Function;
  exports.Hash = Hash;
  exports.Ident = Ident;
  exports.LeftCurlyBracket = LeftCurlyBracket;
  exports.LeftParenthesis = LeftParenthesis;
  exports.LeftSquareBracket = LeftSquareBracket;
  exports.Number = Number2;
  exports.Percentage = Percentage;
  exports.RightCurlyBracket = RightCurlyBracket;
  exports.RightParenthesis = RightParenthesis;
  exports.RightSquareBracket = RightSquareBracket;
  exports.Semicolon = Semicolon;
  exports.String = String2;
  exports.Url = Url;
  exports.WhiteSpace = WhiteSpace;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/char-code-definitions.cjs
var require_char_code_definitions = __commonJS((exports) => {
  var EOF = 0;
  function isDigit(code) {
    return code >= 48 && code <= 57;
  }
  function isHexDigit(code) {
    return isDigit(code) || code >= 65 && code <= 70 || code >= 97 && code <= 102;
  }
  function isUppercaseLetter(code) {
    return code >= 65 && code <= 90;
  }
  function isLowercaseLetter(code) {
    return code >= 97 && code <= 122;
  }
  function isLetter(code) {
    return isUppercaseLetter(code) || isLowercaseLetter(code);
  }
  function isNonAscii(code) {
    return code >= 128;
  }
  function isNameStart(code) {
    return isLetter(code) || isNonAscii(code) || code === 95;
  }
  function isName(code) {
    return isNameStart(code) || isDigit(code) || code === 45;
  }
  function isNonPrintable(code) {
    return code >= 0 && code <= 8 || code === 11 || code >= 14 && code <= 31 || code === 127;
  }
  function isNewline(code) {
    return code === 10 || code === 13 || code === 12;
  }
  function isWhiteSpace(code) {
    return isNewline(code) || code === 32 || code === 9;
  }
  function isValidEscape(first, second) {
    if (first !== 92) {
      return false;
    }
    if (isNewline(second) || second === EOF) {
      return false;
    }
    return true;
  }
  function isIdentifierStart(first, second, third) {
    if (first === 45) {
      return isNameStart(second) || second === 45 || isValidEscape(second, third);
    }
    if (isNameStart(first)) {
      return true;
    }
    if (first === 92) {
      return isValidEscape(first, second);
    }
    return false;
  }
  function isNumberStart(first, second, third) {
    if (first === 43 || first === 45) {
      if (isDigit(second)) {
        return 2;
      }
      return second === 46 && isDigit(third) ? 3 : 0;
    }
    if (first === 46) {
      return isDigit(second) ? 2 : 0;
    }
    if (isDigit(first)) {
      return 1;
    }
    return 0;
  }
  function isBOM(code) {
    if (code === 65279) {
      return 1;
    }
    if (code === 65534) {
      return 1;
    }
    return 0;
  }
  var CATEGORY = new Array(128);
  var EofCategory = 128;
  var WhiteSpaceCategory = 130;
  var DigitCategory = 131;
  var NameStartCategory = 132;
  var NonPrintableCategory = 133;
  for (let i = 0;i < CATEGORY.length; i++) {
    CATEGORY[i] = isWhiteSpace(i) && WhiteSpaceCategory || isDigit(i) && DigitCategory || isNameStart(i) && NameStartCategory || isNonPrintable(i) && NonPrintableCategory || i || EofCategory;
  }
  function charCodeCategory(code) {
    return code < 128 ? CATEGORY[code] : NameStartCategory;
  }
  exports.DigitCategory = DigitCategory;
  exports.EofCategory = EofCategory;
  exports.NameStartCategory = NameStartCategory;
  exports.NonPrintableCategory = NonPrintableCategory;
  exports.WhiteSpaceCategory = WhiteSpaceCategory;
  exports.charCodeCategory = charCodeCategory;
  exports.isBOM = isBOM;
  exports.isDigit = isDigit;
  exports.isHexDigit = isHexDigit;
  exports.isIdentifierStart = isIdentifierStart;
  exports.isLetter = isLetter;
  exports.isLowercaseLetter = isLowercaseLetter;
  exports.isName = isName;
  exports.isNameStart = isNameStart;
  exports.isNewline = isNewline;
  exports.isNonAscii = isNonAscii;
  exports.isNonPrintable = isNonPrintable;
  exports.isNumberStart = isNumberStart;
  exports.isUppercaseLetter = isUppercaseLetter;
  exports.isValidEscape = isValidEscape;
  exports.isWhiteSpace = isWhiteSpace;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/utils.cjs
var require_utils = __commonJS((exports) => {
  var charCodeDefinitions = require_char_code_definitions();
  function getCharCode(source, offset) {
    return offset < source.length ? source.charCodeAt(offset) : 0;
  }
  function getNewlineLength(source, offset, code) {
    if (code === 13 && getCharCode(source, offset + 1) === 10) {
      return 2;
    }
    return 1;
  }
  function cmpChar(testStr, offset, referenceCode) {
    let code = testStr.charCodeAt(offset);
    if (charCodeDefinitions.isUppercaseLetter(code)) {
      code = code | 32;
    }
    return code === referenceCode;
  }
  function cmpStr(testStr, start, end, referenceStr) {
    if (end - start !== referenceStr.length) {
      return false;
    }
    if (start < 0 || end > testStr.length) {
      return false;
    }
    for (let i = start;i < end; i++) {
      const referenceCode = referenceStr.charCodeAt(i - start);
      let testCode = testStr.charCodeAt(i);
      if (charCodeDefinitions.isUppercaseLetter(testCode)) {
        testCode = testCode | 32;
      }
      if (testCode !== referenceCode) {
        return false;
      }
    }
    return true;
  }
  function findWhiteSpaceStart(source, offset) {
    for (;offset >= 0; offset--) {
      if (!charCodeDefinitions.isWhiteSpace(source.charCodeAt(offset))) {
        break;
      }
    }
    return offset + 1;
  }
  function findWhiteSpaceEnd(source, offset) {
    for (;offset < source.length; offset++) {
      if (!charCodeDefinitions.isWhiteSpace(source.charCodeAt(offset))) {
        break;
      }
    }
    return offset;
  }
  function findDecimalNumberEnd(source, offset) {
    for (;offset < source.length; offset++) {
      if (!charCodeDefinitions.isDigit(source.charCodeAt(offset))) {
        break;
      }
    }
    return offset;
  }
  function consumeEscaped(source, offset) {
    offset += 2;
    if (charCodeDefinitions.isHexDigit(getCharCode(source, offset - 1))) {
      for (const maxOffset = Math.min(source.length, offset + 5);offset < maxOffset; offset++) {
        if (!charCodeDefinitions.isHexDigit(getCharCode(source, offset))) {
          break;
        }
      }
      const code = getCharCode(source, offset);
      if (charCodeDefinitions.isWhiteSpace(code)) {
        offset += getNewlineLength(source, offset, code);
      }
    }
    return offset;
  }
  function consumeName(source, offset) {
    for (;offset < source.length; offset++) {
      const code = source.charCodeAt(offset);
      if (charCodeDefinitions.isName(code)) {
        continue;
      }
      if (charCodeDefinitions.isValidEscape(code, getCharCode(source, offset + 1))) {
        offset = consumeEscaped(source, offset) - 1;
        continue;
      }
      break;
    }
    return offset;
  }
  function consumeNumber(source, offset) {
    let code = source.charCodeAt(offset);
    if (code === 43 || code === 45) {
      code = source.charCodeAt(offset += 1);
    }
    if (charCodeDefinitions.isDigit(code)) {
      offset = findDecimalNumberEnd(source, offset + 1);
      code = source.charCodeAt(offset);
    }
    if (code === 46 && charCodeDefinitions.isDigit(source.charCodeAt(offset + 1))) {
      offset += 2;
      offset = findDecimalNumberEnd(source, offset);
    }
    if (cmpChar(source, offset, 101)) {
      let sign = 0;
      code = source.charCodeAt(offset + 1);
      if (code === 45 || code === 43) {
        sign = 1;
        code = source.charCodeAt(offset + 2);
      }
      if (charCodeDefinitions.isDigit(code)) {
        offset = findDecimalNumberEnd(source, offset + 1 + sign + 1);
      }
    }
    return offset;
  }
  function consumeBadUrlRemnants(source, offset) {
    for (;offset < source.length; offset++) {
      const code = source.charCodeAt(offset);
      if (code === 41) {
        offset++;
        break;
      }
      if (charCodeDefinitions.isValidEscape(code, getCharCode(source, offset + 1))) {
        offset = consumeEscaped(source, offset);
      }
    }
    return offset;
  }
  function decodeEscaped(escaped) {
    if (escaped.length === 1 && !charCodeDefinitions.isHexDigit(escaped.charCodeAt(0))) {
      return escaped[0];
    }
    let code = parseInt(escaped, 16);
    if (code === 0 || code >= 55296 && code <= 57343 || code > 1114111) {
      code = 65533;
    }
    return String.fromCodePoint(code);
  }
  exports.cmpChar = cmpChar;
  exports.cmpStr = cmpStr;
  exports.consumeBadUrlRemnants = consumeBadUrlRemnants;
  exports.consumeEscaped = consumeEscaped;
  exports.consumeName = consumeName;
  exports.consumeNumber = consumeNumber;
  exports.decodeEscaped = decodeEscaped;
  exports.findDecimalNumberEnd = findDecimalNumberEnd;
  exports.findWhiteSpaceEnd = findWhiteSpaceEnd;
  exports.findWhiteSpaceStart = findWhiteSpaceStart;
  exports.getNewlineLength = getNewlineLength;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/names.cjs
var require_names = __commonJS((exports, module) => {
  var tokenNames = [
    "EOF-token",
    "ident-token",
    "function-token",
    "at-keyword-token",
    "hash-token",
    "string-token",
    "bad-string-token",
    "url-token",
    "bad-url-token",
    "delim-token",
    "number-token",
    "percentage-token",
    "dimension-token",
    "whitespace-token",
    "CDO-token",
    "CDC-token",
    "colon-token",
    "semicolon-token",
    "comma-token",
    "[-token",
    "]-token",
    "(-token",
    ")-token",
    "{-token",
    "}-token",
    "comment-token"
  ];
  module.exports = tokenNames;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/adopt-buffer.cjs
var require_adopt_buffer = __commonJS((exports) => {
  var MIN_SIZE = 16 * 1024;
  function adoptBuffer(buffer = null, size) {
    if (buffer === null || buffer.length < size) {
      return new Uint32Array(Math.max(size + 1024, MIN_SIZE));
    }
    return buffer;
  }
  exports.adoptBuffer = adoptBuffer;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/OffsetToLocation.cjs
var require_OffsetToLocation = __commonJS((exports) => {
  var adoptBuffer = require_adopt_buffer();
  var charCodeDefinitions = require_char_code_definitions();
  var N = 10;
  var F = 12;
  var R = 13;
  function computeLinesAndColumns(host) {
    const source = host.source;
    const sourceLength = source.length;
    const startOffset = source.length > 0 ? charCodeDefinitions.isBOM(source.charCodeAt(0)) : 0;
    const lines = adoptBuffer.adoptBuffer(host.lines, sourceLength);
    const columns = adoptBuffer.adoptBuffer(host.columns, sourceLength);
    let line = host.startLine;
    let column = host.startColumn;
    for (let i = startOffset;i < sourceLength; i++) {
      const code = source.charCodeAt(i);
      lines[i] = line;
      columns[i] = column++;
      if (code === N || code === R || code === F) {
        if (code === R && i + 1 < sourceLength && source.charCodeAt(i + 1) === N) {
          i++;
          lines[i] = line;
          columns[i] = column;
        }
        line++;
        column = 1;
      }
    }
    lines[sourceLength] = line;
    columns[sourceLength] = column;
    host.lines = lines;
    host.columns = columns;
    host.computed = true;
  }

  class OffsetToLocation {
    constructor(source, startOffset, startLine, startColumn) {
      this.setSource(source, startOffset, startLine, startColumn);
      this.lines = null;
      this.columns = null;
    }
    setSource(source = "", startOffset = 0, startLine = 1, startColumn = 1) {
      this.source = source;
      this.startOffset = startOffset;
      this.startLine = startLine;
      this.startColumn = startColumn;
      this.computed = false;
    }
    getLocation(offset, filename) {
      if (!this.computed) {
        computeLinesAndColumns(this);
      }
      return {
        source: filename,
        offset: this.startOffset + offset,
        line: this.lines[offset],
        column: this.columns[offset]
      };
    }
    getLocationRange(start, end, filename) {
      if (!this.computed) {
        computeLinesAndColumns(this);
      }
      return {
        source: filename,
        start: {
          offset: this.startOffset + start,
          line: this.lines[start],
          column: this.columns[start]
        },
        end: {
          offset: this.startOffset + end,
          line: this.lines[end],
          column: this.columns[end]
        }
      };
    }
  }
  exports.OffsetToLocation = OffsetToLocation;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/TokenStream.cjs
var require_TokenStream = __commonJS((exports) => {
  var adoptBuffer = require_adopt_buffer();
  var utils = require_utils();
  var names = require_names();
  var types2 = require_types();
  var OFFSET_MASK = 16777215;
  var TYPE_SHIFT = 24;
  var BLOCK_OPEN_TOKEN = 1;
  var BLOCK_CLOSE_TOKEN = 2;
  var balancePair = new Uint8Array(32);
  balancePair[types2.Function] = types2.RightParenthesis;
  balancePair[types2.LeftParenthesis] = types2.RightParenthesis;
  balancePair[types2.LeftSquareBracket] = types2.RightSquareBracket;
  balancePair[types2.LeftCurlyBracket] = types2.RightCurlyBracket;
  var blockTokens = new Uint8Array(32);
  blockTokens[types2.Function] = BLOCK_OPEN_TOKEN;
  blockTokens[types2.LeftParenthesis] = BLOCK_OPEN_TOKEN;
  blockTokens[types2.LeftSquareBracket] = BLOCK_OPEN_TOKEN;
  blockTokens[types2.LeftCurlyBracket] = BLOCK_OPEN_TOKEN;
  blockTokens[types2.RightParenthesis] = BLOCK_CLOSE_TOKEN;
  blockTokens[types2.RightSquareBracket] = BLOCK_CLOSE_TOKEN;
  blockTokens[types2.RightCurlyBracket] = BLOCK_CLOSE_TOKEN;
  function boundIndex(index, min, max) {
    return index < min ? min : index > max ? max : index;
  }

  class TokenStream {
    constructor(source, tokenize) {
      this.setSource(source, tokenize);
    }
    reset() {
      this.eof = false;
      this.tokenIndex = -1;
      this.tokenType = 0;
      this.tokenStart = this.firstCharOffset;
      this.tokenEnd = this.firstCharOffset;
    }
    setSource(source = "", tokenize = () => {}) {
      source = String(source || "");
      const sourceLength = source.length;
      const offsetAndType = adoptBuffer.adoptBuffer(this.offsetAndType, source.length + 1);
      const balance = adoptBuffer.adoptBuffer(this.balance, source.length + 1);
      let tokenCount = 0;
      let firstCharOffset = -1;
      let balanceCloseType = 0;
      let balanceStart = source.length;
      this.offsetAndType = null;
      this.balance = null;
      balance.fill(0);
      tokenize(source, (type, start, end) => {
        const index = tokenCount++;
        offsetAndType[index] = type << TYPE_SHIFT | end;
        if (firstCharOffset === -1) {
          firstCharOffset = start;
        }
        balance[index] = balanceStart;
        if (type === balanceCloseType) {
          const prevBalanceStart = balance[balanceStart];
          balance[balanceStart] = index;
          balanceStart = prevBalanceStart;
          balanceCloseType = balancePair[offsetAndType[prevBalanceStart] >> TYPE_SHIFT];
        } else if (this.isBlockOpenerTokenType(type)) {
          balanceStart = index;
          balanceCloseType = balancePair[type];
        }
      });
      offsetAndType[tokenCount] = types2.EOF << TYPE_SHIFT | sourceLength;
      balance[tokenCount] = tokenCount;
      for (let i = 0;i < tokenCount; i++) {
        const balanceStart2 = balance[i];
        if (balanceStart2 <= i) {
          const balanceEnd = balance[balanceStart2];
          if (balanceEnd !== i) {
            balance[i] = balanceEnd;
          }
        } else if (balanceStart2 > tokenCount) {
          balance[i] = tokenCount;
        }
      }
      this.source = source;
      this.firstCharOffset = firstCharOffset === -1 ? 0 : firstCharOffset;
      this.tokenCount = tokenCount;
      this.offsetAndType = offsetAndType;
      this.balance = balance;
      this.reset();
      this.next();
    }
    lookupType(offset) {
      offset += this.tokenIndex;
      if (offset < this.tokenCount) {
        return this.offsetAndType[offset] >> TYPE_SHIFT;
      }
      return types2.EOF;
    }
    lookupTypeNonSC(idx) {
      for (let offset = this.tokenIndex;offset < this.tokenCount; offset++) {
        const tokenType = this.offsetAndType[offset] >> TYPE_SHIFT;
        if (tokenType !== types2.WhiteSpace && tokenType !== types2.Comment) {
          if (idx-- === 0) {
            return tokenType;
          }
        }
      }
      return types2.EOF;
    }
    lookupOffset(offset) {
      offset += this.tokenIndex;
      if (offset < this.tokenCount) {
        return this.offsetAndType[offset - 1] & OFFSET_MASK;
      }
      return this.source.length;
    }
    lookupOffsetNonSC(idx) {
      for (let offset = this.tokenIndex;offset < this.tokenCount; offset++) {
        const tokenType = this.offsetAndType[offset] >> TYPE_SHIFT;
        if (tokenType !== types2.WhiteSpace && tokenType !== types2.Comment) {
          if (idx-- === 0) {
            return offset - this.tokenIndex;
          }
        }
      }
      return types2.EOF;
    }
    lookupValue(offset, referenceStr) {
      offset += this.tokenIndex;
      if (offset < this.tokenCount) {
        return utils.cmpStr(this.source, this.offsetAndType[offset - 1] & OFFSET_MASK, this.offsetAndType[offset] & OFFSET_MASK, referenceStr);
      }
      return false;
    }
    getTokenStart(tokenIndex) {
      if (tokenIndex === this.tokenIndex) {
        return this.tokenStart;
      }
      if (tokenIndex > 0) {
        return tokenIndex < this.tokenCount ? this.offsetAndType[tokenIndex - 1] & OFFSET_MASK : this.offsetAndType[this.tokenCount] & OFFSET_MASK;
      }
      return this.firstCharOffset;
    }
    getTokenEnd(tokenIndex) {
      if (tokenIndex === this.tokenIndex) {
        return this.tokenEnd;
      }
      return this.offsetAndType[boundIndex(tokenIndex, 0, this.tokenCount)] & OFFSET_MASK;
    }
    getTokenType(tokenIndex) {
      if (tokenIndex === this.tokenIndex) {
        return this.tokenType;
      }
      return this.offsetAndType[boundIndex(tokenIndex, 0, this.tokenCount)] >> TYPE_SHIFT;
    }
    substrToCursor(start) {
      return this.source.substring(start, this.tokenStart);
    }
    isBlockOpenerTokenType(tokenType) {
      return blockTokens[tokenType] === BLOCK_OPEN_TOKEN;
    }
    isBlockCloserTokenType(tokenType) {
      return blockTokens[tokenType] === BLOCK_CLOSE_TOKEN;
    }
    getBlockTokenPairIndex(tokenIndex) {
      const type = this.getTokenType(tokenIndex);
      if (blockTokens[type] === 1) {
        const pairIndex = this.balance[tokenIndex];
        const closeType = this.getTokenType(pairIndex);
        return balancePair[type] === closeType ? pairIndex : -1;
      } else if (blockTokens[type] === 2) {
        const pairIndex = this.balance[tokenIndex];
        const openType = this.getTokenType(pairIndex);
        return balancePair[openType] === type ? pairIndex : -1;
      }
      return -1;
    }
    isBalanceEdge(tokenIndex) {
      return this.balance[this.tokenIndex] < tokenIndex;
    }
    isDelim(code, offset) {
      if (offset) {
        return this.lookupType(offset) === types2.Delim && this.source.charCodeAt(this.lookupOffset(offset)) === code;
      }
      return this.tokenType === types2.Delim && this.source.charCodeAt(this.tokenStart) === code;
    }
    skip(tokenCount) {
      let next = this.tokenIndex + tokenCount;
      if (next < this.tokenCount) {
        this.tokenIndex = next;
        this.tokenStart = this.offsetAndType[next - 1] & OFFSET_MASK;
        next = this.offsetAndType[next];
        this.tokenType = next >> TYPE_SHIFT;
        this.tokenEnd = next & OFFSET_MASK;
      } else {
        this.tokenIndex = this.tokenCount;
        this.next();
      }
    }
    next() {
      let next = this.tokenIndex + 1;
      if (next < this.tokenCount) {
        this.tokenIndex = next;
        this.tokenStart = this.tokenEnd;
        next = this.offsetAndType[next];
        this.tokenType = next >> TYPE_SHIFT;
        this.tokenEnd = next & OFFSET_MASK;
      } else {
        this.eof = true;
        this.tokenIndex = this.tokenCount;
        this.tokenType = types2.EOF;
        this.tokenStart = this.tokenEnd = this.source.length;
      }
    }
    skipSC() {
      while (this.tokenType === types2.WhiteSpace || this.tokenType === types2.Comment) {
        this.next();
      }
    }
    skipUntilBalanced(startToken, stopConsume) {
      let cursor = startToken;
      let balanceEnd = 0;
      let offset = 0;
      loop:
        for (;cursor < this.tokenCount; cursor++) {
          balanceEnd = this.balance[cursor];
          if (balanceEnd < startToken) {
            break loop;
          }
          offset = cursor > 0 ? this.offsetAndType[cursor - 1] & OFFSET_MASK : this.firstCharOffset;
          switch (stopConsume(this.source.charCodeAt(offset))) {
            case 1:
              break loop;
            case 2:
              cursor++;
              break loop;
            default:
              if (this.isBlockOpenerTokenType(this.offsetAndType[cursor] >> TYPE_SHIFT)) {
                cursor = balanceEnd;
              }
          }
        }
      this.skip(cursor - this.tokenIndex);
    }
    forEachToken(fn) {
      for (let i = 0, offset = this.firstCharOffset;i < this.tokenCount; i++) {
        const start = offset;
        const item = this.offsetAndType[i];
        const end = item & OFFSET_MASK;
        const type = item >> TYPE_SHIFT;
        offset = end;
        fn(type, start, end, i);
      }
    }
    dump() {
      const tokens = new Array(this.tokenCount);
      this.forEachToken((type, start, end, index) => {
        tokens[index] = {
          idx: index,
          type: names[type],
          chunk: this.source.substring(start, end),
          balance: this.balance[index]
        };
      });
      return tokens;
    }
  }
  exports.TokenStream = TokenStream;
});

// ../imp-pinned/node_modules/css-tree/cjs/tokenizer/index.cjs
var require_tokenizer = __commonJS((exports) => {
  var types2 = require_types();
  var charCodeDefinitions = require_char_code_definitions();
  var utils = require_utils();
  var names = require_names();
  var OffsetToLocation = require_OffsetToLocation();
  var TokenStream = require_TokenStream();
  function tokenize(source, onToken) {
    function getCharCode(offset2) {
      return offset2 < sourceLength ? source.charCodeAt(offset2) : 0;
    }
    function consumeNumericToken() {
      offset = utils.consumeNumber(source, offset);
      if (charCodeDefinitions.isIdentifierStart(getCharCode(offset), getCharCode(offset + 1), getCharCode(offset + 2))) {
        type = types2.Dimension;
        offset = utils.consumeName(source, offset);
        return;
      }
      if (getCharCode(offset) === 37) {
        type = types2.Percentage;
        offset++;
        return;
      }
      type = types2.Number;
    }
    function consumeIdentLikeToken() {
      const nameStartOffset = offset;
      offset = utils.consumeName(source, offset);
      if (utils.cmpStr(source, nameStartOffset, offset, "url") && getCharCode(offset) === 40) {
        offset = utils.findWhiteSpaceEnd(source, offset + 1);
        if (getCharCode(offset) === 34 || getCharCode(offset) === 39) {
          type = types2.Function;
          offset = nameStartOffset + 4;
          return;
        }
        consumeUrlToken();
        return;
      }
      if (getCharCode(offset) === 40) {
        type = types2.Function;
        offset++;
        return;
      }
      type = types2.Ident;
    }
    function consumeStringToken(endingCodePoint) {
      if (!endingCodePoint) {
        endingCodePoint = getCharCode(offset++);
      }
      type = types2.String;
      for (;offset < source.length; offset++) {
        const code = source.charCodeAt(offset);
        switch (charCodeDefinitions.charCodeCategory(code)) {
          case endingCodePoint:
            offset++;
            return;
          case charCodeDefinitions.WhiteSpaceCategory:
            if (charCodeDefinitions.isNewline(code)) {
              offset += utils.getNewlineLength(source, offset, code);
              type = types2.BadString;
              return;
            }
            break;
          case 92:
            if (offset === source.length - 1) {
              break;
            }
            const nextCode = getCharCode(offset + 1);
            if (charCodeDefinitions.isNewline(nextCode)) {
              offset += utils.getNewlineLength(source, offset + 1, nextCode);
            } else if (charCodeDefinitions.isValidEscape(code, nextCode)) {
              offset = utils.consumeEscaped(source, offset) - 1;
            }
            break;
        }
      }
    }
    function consumeUrlToken() {
      type = types2.Url;
      offset = utils.findWhiteSpaceEnd(source, offset);
      for (;offset < source.length; offset++) {
        const code = source.charCodeAt(offset);
        switch (charCodeDefinitions.charCodeCategory(code)) {
          case 41:
            offset++;
            return;
          case charCodeDefinitions.WhiteSpaceCategory:
            offset = utils.findWhiteSpaceEnd(source, offset);
            if (getCharCode(offset) === 41 || offset >= source.length) {
              if (offset < source.length) {
                offset++;
              }
              return;
            }
            offset = utils.consumeBadUrlRemnants(source, offset);
            type = types2.BadUrl;
            return;
          case 34:
          case 39:
          case 40:
          case charCodeDefinitions.NonPrintableCategory:
            offset = utils.consumeBadUrlRemnants(source, offset);
            type = types2.BadUrl;
            return;
          case 92:
            if (charCodeDefinitions.isValidEscape(code, getCharCode(offset + 1))) {
              offset = utils.consumeEscaped(source, offset) - 1;
              break;
            }
            offset = utils.consumeBadUrlRemnants(source, offset);
            type = types2.BadUrl;
            return;
        }
      }
    }
    source = String(source || "");
    const sourceLength = source.length;
    let start = charCodeDefinitions.isBOM(getCharCode(0));
    let offset = start;
    let type;
    while (offset < sourceLength) {
      const code = source.charCodeAt(offset);
      switch (charCodeDefinitions.charCodeCategory(code)) {
        case charCodeDefinitions.WhiteSpaceCategory:
          type = types2.WhiteSpace;
          offset = utils.findWhiteSpaceEnd(source, offset + 1);
          break;
        case 34:
          consumeStringToken();
          break;
        case 35:
          if (charCodeDefinitions.isName(getCharCode(offset + 1)) || charCodeDefinitions.isValidEscape(getCharCode(offset + 1), getCharCode(offset + 2))) {
            type = types2.Hash;
            offset = utils.consumeName(source, offset + 1);
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 39:
          consumeStringToken();
          break;
        case 40:
          type = types2.LeftParenthesis;
          offset++;
          break;
        case 41:
          type = types2.RightParenthesis;
          offset++;
          break;
        case 43:
          if (charCodeDefinitions.isNumberStart(code, getCharCode(offset + 1), getCharCode(offset + 2))) {
            consumeNumericToken();
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 44:
          type = types2.Comma;
          offset++;
          break;
        case 45:
          if (charCodeDefinitions.isNumberStart(code, getCharCode(offset + 1), getCharCode(offset + 2))) {
            consumeNumericToken();
          } else {
            if (getCharCode(offset + 1) === 45 && getCharCode(offset + 2) === 62) {
              type = types2.CDC;
              offset = offset + 3;
            } else {
              if (charCodeDefinitions.isIdentifierStart(code, getCharCode(offset + 1), getCharCode(offset + 2))) {
                consumeIdentLikeToken();
              } else {
                type = types2.Delim;
                offset++;
              }
            }
          }
          break;
        case 46:
          if (charCodeDefinitions.isNumberStart(code, getCharCode(offset + 1), getCharCode(offset + 2))) {
            consumeNumericToken();
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 47:
          if (getCharCode(offset + 1) === 42) {
            type = types2.Comment;
            offset = source.indexOf("*/", offset + 2);
            offset = offset === -1 ? source.length : offset + 2;
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 58:
          type = types2.Colon;
          offset++;
          break;
        case 59:
          type = types2.Semicolon;
          offset++;
          break;
        case 60:
          if (getCharCode(offset + 1) === 33 && getCharCode(offset + 2) === 45 && getCharCode(offset + 3) === 45) {
            type = types2.CDO;
            offset = offset + 4;
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 64:
          if (charCodeDefinitions.isIdentifierStart(getCharCode(offset + 1), getCharCode(offset + 2), getCharCode(offset + 3))) {
            type = types2.AtKeyword;
            offset = utils.consumeName(source, offset + 1);
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 91:
          type = types2.LeftSquareBracket;
          offset++;
          break;
        case 92:
          if (charCodeDefinitions.isValidEscape(code, getCharCode(offset + 1))) {
            consumeIdentLikeToken();
          } else {
            type = types2.Delim;
            offset++;
          }
          break;
        case 93:
          type = types2.RightSquareBracket;
          offset++;
          break;
        case 123:
          type = types2.LeftCurlyBracket;
          offset++;
          break;
        case 125:
          type = types2.RightCurlyBracket;
          offset++;
          break;
        case charCodeDefinitions.DigitCategory:
          consumeNumericToken();
          break;
        case charCodeDefinitions.NameStartCategory:
          consumeIdentLikeToken();
          break;
        default:
          type = types2.Delim;
          offset++;
      }
      onToken(type, start, start = offset);
    }
  }
  exports.AtKeyword = types2.AtKeyword;
  exports.BadString = types2.BadString;
  exports.BadUrl = types2.BadUrl;
  exports.CDC = types2.CDC;
  exports.CDO = types2.CDO;
  exports.Colon = types2.Colon;
  exports.Comma = types2.Comma;
  exports.Comment = types2.Comment;
  exports.Delim = types2.Delim;
  exports.Dimension = types2.Dimension;
  exports.EOF = types2.EOF;
  exports.Function = types2.Function;
  exports.Hash = types2.Hash;
  exports.Ident = types2.Ident;
  exports.LeftCurlyBracket = types2.LeftCurlyBracket;
  exports.LeftParenthesis = types2.LeftParenthesis;
  exports.LeftSquareBracket = types2.LeftSquareBracket;
  exports.Number = types2.Number;
  exports.Percentage = types2.Percentage;
  exports.RightCurlyBracket = types2.RightCurlyBracket;
  exports.RightParenthesis = types2.RightParenthesis;
  exports.RightSquareBracket = types2.RightSquareBracket;
  exports.Semicolon = types2.Semicolon;
  exports.String = types2.String;
  exports.Url = types2.Url;
  exports.WhiteSpace = types2.WhiteSpace;
  exports.tokenTypes = types2;
  exports.DigitCategory = charCodeDefinitions.DigitCategory;
  exports.EofCategory = charCodeDefinitions.EofCategory;
  exports.NameStartCategory = charCodeDefinitions.NameStartCategory;
  exports.NonPrintableCategory = charCodeDefinitions.NonPrintableCategory;
  exports.WhiteSpaceCategory = charCodeDefinitions.WhiteSpaceCategory;
  exports.charCodeCategory = charCodeDefinitions.charCodeCategory;
  exports.isBOM = charCodeDefinitions.isBOM;
  exports.isDigit = charCodeDefinitions.isDigit;
  exports.isHexDigit = charCodeDefinitions.isHexDigit;
  exports.isIdentifierStart = charCodeDefinitions.isIdentifierStart;
  exports.isLetter = charCodeDefinitions.isLetter;
  exports.isLowercaseLetter = charCodeDefinitions.isLowercaseLetter;
  exports.isName = charCodeDefinitions.isName;
  exports.isNameStart = charCodeDefinitions.isNameStart;
  exports.isNewline = charCodeDefinitions.isNewline;
  exports.isNonAscii = charCodeDefinitions.isNonAscii;
  exports.isNonPrintable = charCodeDefinitions.isNonPrintable;
  exports.isNumberStart = charCodeDefinitions.isNumberStart;
  exports.isUppercaseLetter = charCodeDefinitions.isUppercaseLetter;
  exports.isValidEscape = charCodeDefinitions.isValidEscape;
  exports.isWhiteSpace = charCodeDefinitions.isWhiteSpace;
  exports.cmpChar = utils.cmpChar;
  exports.cmpStr = utils.cmpStr;
  exports.consumeBadUrlRemnants = utils.consumeBadUrlRemnants;
  exports.consumeEscaped = utils.consumeEscaped;
  exports.consumeName = utils.consumeName;
  exports.consumeNumber = utils.consumeNumber;
  exports.decodeEscaped = utils.decodeEscaped;
  exports.findDecimalNumberEnd = utils.findDecimalNumberEnd;
  exports.findWhiteSpaceEnd = utils.findWhiteSpaceEnd;
  exports.findWhiteSpaceStart = utils.findWhiteSpaceStart;
  exports.getNewlineLength = utils.getNewlineLength;
  exports.tokenNames = names;
  exports.OffsetToLocation = OffsetToLocation.OffsetToLocation;
  exports.TokenStream = TokenStream.TokenStream;
  exports.tokenize = tokenize;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/List.cjs
var require_List = __commonJS((exports) => {
  var releasedCursors = null;

  class List {
    static createItem(data) {
      return {
        prev: null,
        next: null,
        data
      };
    }
    constructor() {
      this.head = null;
      this.tail = null;
      this.cursor = null;
    }
    createItem(data) {
      return List.createItem(data);
    }
    allocateCursor(prev, next) {
      let cursor;
      if (releasedCursors !== null) {
        cursor = releasedCursors;
        releasedCursors = releasedCursors.cursor;
        cursor.prev = prev;
        cursor.next = next;
        cursor.cursor = this.cursor;
      } else {
        cursor = {
          prev,
          next,
          cursor: this.cursor
        };
      }
      this.cursor = cursor;
      return cursor;
    }
    releaseCursor() {
      const { cursor } = this;
      this.cursor = cursor.cursor;
      cursor.prev = null;
      cursor.next = null;
      cursor.cursor = releasedCursors;
      releasedCursors = cursor;
    }
    updateCursors(prevOld, prevNew, nextOld, nextNew) {
      let { cursor } = this;
      while (cursor !== null) {
        if (cursor.prev === prevOld) {
          cursor.prev = prevNew;
        }
        if (cursor.next === nextOld) {
          cursor.next = nextNew;
        }
        cursor = cursor.cursor;
      }
    }
    *[Symbol.iterator]() {
      for (let cursor = this.head;cursor !== null; cursor = cursor.next) {
        yield cursor.data;
      }
    }
    get size() {
      let size = 0;
      for (let cursor = this.head;cursor !== null; cursor = cursor.next) {
        size++;
      }
      return size;
    }
    get isEmpty() {
      return this.head === null;
    }
    get first() {
      return this.head && this.head.data;
    }
    get last() {
      return this.tail && this.tail.data;
    }
    fromArray(array) {
      let cursor = null;
      this.head = null;
      for (let data of array) {
        const item = List.createItem(data);
        if (cursor !== null) {
          cursor.next = item;
        } else {
          this.head = item;
        }
        item.prev = cursor;
        cursor = item;
      }
      this.tail = cursor;
      return this;
    }
    toArray() {
      return [...this];
    }
    toJSON() {
      return [...this];
    }
    forEach(fn, thisArg = this) {
      const cursor = this.allocateCursor(null, this.head);
      while (cursor.next !== null) {
        const item = cursor.next;
        cursor.next = item.next;
        fn.call(thisArg, item.data, item, this);
      }
      this.releaseCursor();
    }
    forEachRight(fn, thisArg = this) {
      const cursor = this.allocateCursor(this.tail, null);
      while (cursor.prev !== null) {
        const item = cursor.prev;
        cursor.prev = item.prev;
        fn.call(thisArg, item.data, item, this);
      }
      this.releaseCursor();
    }
    reduce(fn, initialValue, thisArg = this) {
      let cursor = this.allocateCursor(null, this.head);
      let acc = initialValue;
      let item;
      while (cursor.next !== null) {
        item = cursor.next;
        cursor.next = item.next;
        acc = fn.call(thisArg, acc, item.data, item, this);
      }
      this.releaseCursor();
      return acc;
    }
    reduceRight(fn, initialValue, thisArg = this) {
      let cursor = this.allocateCursor(this.tail, null);
      let acc = initialValue;
      let item;
      while (cursor.prev !== null) {
        item = cursor.prev;
        cursor.prev = item.prev;
        acc = fn.call(thisArg, acc, item.data, item, this);
      }
      this.releaseCursor();
      return acc;
    }
    some(fn, thisArg = this) {
      for (let cursor = this.head;cursor !== null; cursor = cursor.next) {
        if (fn.call(thisArg, cursor.data, cursor, this)) {
          return true;
        }
      }
      return false;
    }
    map(fn, thisArg = this) {
      const result = new List;
      for (let cursor = this.head;cursor !== null; cursor = cursor.next) {
        result.appendData(fn.call(thisArg, cursor.data, cursor, this));
      }
      return result;
    }
    filter(fn, thisArg = this) {
      const result = new List;
      for (let cursor = this.head;cursor !== null; cursor = cursor.next) {
        if (fn.call(thisArg, cursor.data, cursor, this)) {
          result.appendData(cursor.data);
        }
      }
      return result;
    }
    nextUntil(start, fn, thisArg = this) {
      if (start === null) {
        return;
      }
      const cursor = this.allocateCursor(null, start);
      while (cursor.next !== null) {
        const item = cursor.next;
        cursor.next = item.next;
        if (fn.call(thisArg, item.data, item, this)) {
          break;
        }
      }
      this.releaseCursor();
    }
    prevUntil(start, fn, thisArg = this) {
      if (start === null) {
        return;
      }
      const cursor = this.allocateCursor(start, null);
      while (cursor.prev !== null) {
        const item = cursor.prev;
        cursor.prev = item.prev;
        if (fn.call(thisArg, item.data, item, this)) {
          break;
        }
      }
      this.releaseCursor();
    }
    clear() {
      this.head = null;
      this.tail = null;
    }
    copy() {
      const result = new List;
      for (let data of this) {
        result.appendData(data);
      }
      return result;
    }
    prepend(item) {
      this.updateCursors(null, item, this.head, item);
      if (this.head !== null) {
        this.head.prev = item;
        item.next = this.head;
      } else {
        this.tail = item;
      }
      this.head = item;
      return this;
    }
    prependData(data) {
      return this.prepend(List.createItem(data));
    }
    append(item) {
      return this.insert(item);
    }
    appendData(data) {
      return this.insert(List.createItem(data));
    }
    insert(item, before = null) {
      if (before !== null) {
        this.updateCursors(before.prev, item, before, item);
        if (before.prev === null) {
          if (this.head !== before) {
            throw new Error("before doesn't belong to list");
          }
          this.head = item;
          before.prev = item;
          item.next = before;
          this.updateCursors(null, item);
        } else {
          before.prev.next = item;
          item.prev = before.prev;
          before.prev = item;
          item.next = before;
        }
      } else {
        this.updateCursors(this.tail, item, null, item);
        if (this.tail !== null) {
          this.tail.next = item;
          item.prev = this.tail;
        } else {
          this.head = item;
        }
        this.tail = item;
      }
      return this;
    }
    insertData(data, before) {
      return this.insert(List.createItem(data), before);
    }
    remove(item) {
      this.updateCursors(item, item.prev, item, item.next);
      if (item.prev !== null) {
        item.prev.next = item.next;
      } else {
        if (this.head !== item) {
          throw new Error("item doesn't belong to list");
        }
        this.head = item.next;
      }
      if (item.next !== null) {
        item.next.prev = item.prev;
      } else {
        if (this.tail !== item) {
          throw new Error("item doesn't belong to list");
        }
        this.tail = item.prev;
      }
      item.prev = null;
      item.next = null;
      return item;
    }
    push(data) {
      this.insert(List.createItem(data));
    }
    pop() {
      return this.tail !== null ? this.remove(this.tail) : null;
    }
    unshift(data) {
      this.prepend(List.createItem(data));
    }
    shift() {
      return this.head !== null ? this.remove(this.head) : null;
    }
    prependList(list) {
      return this.insertList(list, this.head);
    }
    appendList(list) {
      return this.insertList(list);
    }
    insertList(list, before) {
      if (list.head === null) {
        return this;
      }
      if (before !== undefined && before !== null) {
        this.updateCursors(before.prev, list.tail, before, list.head);
        if (before.prev !== null) {
          before.prev.next = list.head;
          list.head.prev = before.prev;
        } else {
          this.head = list.head;
        }
        before.prev = list.tail;
        list.tail.next = before;
      } else {
        this.updateCursors(this.tail, list.tail, null, list.head);
        if (this.tail !== null) {
          this.tail.next = list.head;
          list.head.prev = this.tail;
        } else {
          this.head = list.head;
        }
        this.tail = list.tail;
      }
      list.head = null;
      list.tail = null;
      return this;
    }
    replace(oldItem, newItemOrList) {
      if ("head" in newItemOrList) {
        this.insertList(newItemOrList, oldItem);
      } else {
        this.insert(newItemOrList, oldItem);
      }
      this.remove(oldItem);
    }
  }
  exports.List = List;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/create-custom-error.cjs
var require_create_custom_error = __commonJS((exports) => {
  function createCustomError(name, message) {
    const error = Object.create(SyntaxError.prototype);
    const errorStack = new Error;
    return Object.assign(error, {
      name,
      message,
      get stack() {
        return (errorStack.stack || "").replace(/^(.+\n){1,3}/, `${name}: ${message}
`);
      }
    });
  }
  exports.createCustomError = createCustomError;
});

// ../imp-pinned/node_modules/css-tree/cjs/parser/SyntaxError.cjs
var require_SyntaxError = __commonJS((exports) => {
  var createCustomError = require_create_custom_error();
  var MAX_LINE_LENGTH = 100;
  var OFFSET_CORRECTION = 60;
  var TAB_REPLACEMENT = "    ";
  function sourceFragment({ source, line, column, baseLine, baseColumn }, extraLines) {
    function processLines(start, end) {
      return lines.slice(start, end).map((line2, idx) => String(start + idx + 1).padStart(maxNumLength) + " |" + line2).join(`
`);
    }
    const prelines = `
`.repeat(Math.max(baseLine - 1, 0));
    const precolumns = " ".repeat(Math.max(baseColumn - 1, 0));
    const lines = (prelines + precolumns + source).split(/\r\n?|\n|\f/);
    const startLine = Math.max(1, line - extraLines) - 1;
    const endLine = Math.min(line + extraLines, lines.length + 1);
    const maxNumLength = Math.max(4, String(endLine).length) + 1;
    let cutLeft = 0;
    column += (TAB_REPLACEMENT.length - 1) * (lines[line - 1].substr(0, column - 1).match(/\t/g) || []).length;
    if (column > MAX_LINE_LENGTH) {
      cutLeft = column - OFFSET_CORRECTION + 3;
      column = OFFSET_CORRECTION - 2;
    }
    for (let i = startLine;i <= endLine; i++) {
      if (i >= 0 && i < lines.length) {
        lines[i] = lines[i].replace(/\t/g, TAB_REPLACEMENT);
        lines[i] = (cutLeft > 0 && lines[i].length > cutLeft ? "…" : "") + lines[i].substr(cutLeft, MAX_LINE_LENGTH - 2) + (lines[i].length > cutLeft + MAX_LINE_LENGTH - 1 ? "…" : "");
      }
    }
    return [
      processLines(startLine, line),
      new Array(column + maxNumLength + 2).join("-") + "^",
      processLines(line, endLine)
    ].filter(Boolean).join(`
`).replace(/^(\s+\d+\s+\|\n)+/, "").replace(/\n(\s+\d+\s+\|)+$/, "");
  }
  function SyntaxError2(message, source, offset, line, column, baseLine = 1, baseColumn = 1) {
    const error = Object.assign(createCustomError.createCustomError("SyntaxError", message), {
      source,
      offset,
      line,
      column,
      sourceFragment(extraLines) {
        return sourceFragment({ source, line, column, baseLine, baseColumn }, isNaN(extraLines) ? 0 : extraLines);
      },
      get formattedMessage() {
        return `Parse error: ${message}
` + sourceFragment({ source, line, column, baseLine, baseColumn }, 2);
      }
    });
    return error;
  }
  exports.SyntaxError = SyntaxError2;
});

// ../imp-pinned/node_modules/css-tree/cjs/parser/sequence.cjs
var require_sequence = __commonJS((exports) => {
  var types2 = require_types();
  function readSequence(recognizer) {
    const children = this.createList();
    let space = false;
    const context = {
      recognizer
    };
    while (!this.eof) {
      switch (this.tokenType) {
        case types2.Comment:
          this.next();
          continue;
        case types2.WhiteSpace:
          space = true;
          this.next();
          continue;
      }
      let child = recognizer.getNode.call(this, context);
      if (child === undefined) {
        break;
      }
      if (space) {
        if (recognizer.onWhiteSpace) {
          recognizer.onWhiteSpace.call(this, child, children, context);
        }
        space = false;
      }
      children.push(child);
    }
    if (space && recognizer.onWhiteSpace) {
      recognizer.onWhiteSpace.call(this, null, children, context);
    }
    return children;
  }
  exports.readSequence = readSequence;
});

// ../imp-pinned/node_modules/css-tree/cjs/parser/create.cjs
var require_create = __commonJS((exports) => {
  var List = require_List();
  var SyntaxError2 = require_SyntaxError();
  var index = require_tokenizer();
  var sequence = require_sequence();
  var OffsetToLocation = require_OffsetToLocation();
  var TokenStream = require_TokenStream();
  var utils = require_utils();
  var types2 = require_types();
  var names = require_names();
  var NOOP = () => {};
  var EXCLAMATIONMARK = 33;
  var NUMBERSIGN = 35;
  var SEMICOLON = 59;
  var LEFTCURLYBRACKET = 123;
  var NULL = 0;
  var arrayMethods = {
    createList() {
      return [];
    },
    createSingleNodeList(node2) {
      return [node2];
    },
    getFirstListNode(list) {
      return list && list[0] || null;
    },
    getLastListNode(list) {
      return list && list.length > 0 ? list[list.length - 1] : null;
    }
  };
  var listMethods = {
    createList() {
      return new List.List;
    },
    createSingleNodeList(node2) {
      return new List.List().appendData(node2);
    },
    getFirstListNode(list) {
      return list && list.first;
    },
    getLastListNode(list) {
      return list && list.last;
    }
  };
  function createParseContext(name) {
    return function() {
      return this[name]();
    };
  }
  function fetchParseValues(dict) {
    const result = Object.create(null);
    for (const name of Object.keys(dict)) {
      const item = dict[name];
      const fn = item.parse || item;
      if (fn) {
        result[name] = fn;
      }
    }
    return result;
  }
  function processConfig(config) {
    const parseConfig = {
      context: Object.create(null),
      features: Object.assign(Object.create(null), config.features),
      scope: Object.assign(Object.create(null), config.scope),
      atrule: fetchParseValues(config.atrule),
      pseudo: fetchParseValues(config.pseudo),
      node: fetchParseValues(config.node)
    };
    for (const [name, context] of Object.entries(config.parseContext)) {
      switch (typeof context) {
        case "function":
          parseConfig.context[name] = context;
          break;
        case "string":
          parseConfig.context[name] = createParseContext(context);
          break;
      }
    }
    return {
      config: parseConfig,
      ...parseConfig,
      ...parseConfig.node
    };
  }
  function createParser(config) {
    let source = "";
    let filename = "<unknown>";
    let needPositions = false;
    let onParseError = NOOP;
    let onParseErrorThrow = false;
    const locationMap = new OffsetToLocation.OffsetToLocation;
    const parser = Object.assign(new TokenStream.TokenStream, processConfig(config || {}), {
      parseAtrulePrelude: true,
      parseRulePrelude: true,
      parseValue: true,
      parseCustomProperty: false,
      readSequence: sequence.readSequence,
      consumeUntilBalanceEnd: () => 0,
      consumeUntilLeftCurlyBracket(code) {
        return code === LEFTCURLYBRACKET ? 1 : 0;
      },
      consumeUntilLeftCurlyBracketOrSemicolon(code) {
        return code === LEFTCURLYBRACKET || code === SEMICOLON ? 1 : 0;
      },
      consumeUntilExclamationMarkOrSemicolon(code) {
        return code === EXCLAMATIONMARK || code === SEMICOLON ? 1 : 0;
      },
      consumeUntilSemicolonIncluded(code) {
        return code === SEMICOLON ? 2 : 0;
      },
      createList: NOOP,
      createSingleNodeList: NOOP,
      getFirstListNode: NOOP,
      getLastListNode: NOOP,
      parseWithFallback(consumer, fallback) {
        const startIndex = this.tokenIndex;
        try {
          return consumer.call(this);
        } catch (e) {
          if (onParseErrorThrow) {
            throw e;
          }
          this.skip(startIndex - this.tokenIndex);
          const fallbackNode = fallback.call(this);
          onParseErrorThrow = true;
          onParseError(e, fallbackNode);
          onParseErrorThrow = false;
          return fallbackNode;
        }
      },
      lookupNonWSType(offset) {
        let type;
        do {
          type = this.lookupType(offset++);
          if (type !== types2.WhiteSpace && type !== types2.Comment) {
            return type;
          }
        } while (type !== NULL);
        return NULL;
      },
      charCodeAt(offset) {
        return offset >= 0 && offset < source.length ? source.charCodeAt(offset) : 0;
      },
      substring(offsetStart, offsetEnd) {
        return source.substring(offsetStart, offsetEnd);
      },
      substrToCursor(start) {
        return this.source.substring(start, this.tokenStart);
      },
      cmpChar(offset, charCode) {
        return utils.cmpChar(source, offset, charCode);
      },
      cmpStr(offsetStart, offsetEnd, str) {
        return utils.cmpStr(source, offsetStart, offsetEnd, str);
      },
      consume(tokenType) {
        const start = this.tokenStart;
        this.eat(tokenType);
        return this.substrToCursor(start);
      },
      consumeFunctionName() {
        const name = source.substring(this.tokenStart, this.tokenEnd - 1);
        this.eat(types2.Function);
        return name;
      },
      consumeNumber(type) {
        const number = source.substring(this.tokenStart, utils.consumeNumber(source, this.tokenStart));
        this.eat(type);
        return number;
      },
      eat(tokenType) {
        if (this.tokenType !== tokenType) {
          const tokenName = names[tokenType].slice(0, -6).replace(/-/g, " ").replace(/^./, (m) => m.toUpperCase());
          let message = `${/[[\](){}]/.test(tokenName) ? `"${tokenName}"` : tokenName} is expected`;
          let offset = this.tokenStart;
          switch (tokenType) {
            case types2.Ident:
              if (this.tokenType === types2.Function || this.tokenType === types2.Url) {
                offset = this.tokenEnd - 1;
                message = "Identifier is expected but function found";
              } else {
                message = "Identifier is expected";
              }
              break;
            case types2.Hash:
              if (this.isDelim(NUMBERSIGN)) {
                this.next();
                offset++;
                message = "Name is expected";
              }
              break;
            case types2.Percentage:
              if (this.tokenType === types2.Number) {
                offset = this.tokenEnd;
                message = "Percent sign is expected";
              }
              break;
          }
          this.error(message, offset);
        }
        this.next();
      },
      eatIdent(name) {
        if (this.tokenType !== types2.Ident || this.lookupValue(0, name) === false) {
          this.error(`Identifier "${name}" is expected`);
        }
        this.next();
      },
      eatDelim(code) {
        if (!this.isDelim(code)) {
          this.error(`Delim "${String.fromCharCode(code)}" is expected`);
        }
        this.next();
      },
      getLocation(start, end) {
        if (needPositions) {
          return locationMap.getLocationRange(start, end, filename);
        }
        return null;
      },
      getLocationFromList(list) {
        if (needPositions) {
          const head = this.getFirstListNode(list);
          const tail = this.getLastListNode(list);
          return locationMap.getLocationRange(head !== null ? head.loc.start.offset - locationMap.startOffset : this.tokenStart, tail !== null ? tail.loc.end.offset - locationMap.startOffset : this.tokenStart, filename);
        }
        return null;
      },
      error(message, offset) {
        const location = typeof offset !== "undefined" && offset < source.length ? locationMap.getLocation(offset) : this.eof ? locationMap.getLocation(utils.findWhiteSpaceStart(source, source.length - 1)) : locationMap.getLocation(this.tokenStart);
        throw new SyntaxError2.SyntaxError(message || "Unexpected input", source, location.offset, location.line, location.column, locationMap.startLine, locationMap.startColumn);
      }
    });
    const createTokenIterateAPI = () => ({
      filename,
      source,
      tokenCount: parser.tokenCount,
      getTokenType: (index2) => parser.getTokenType(index2),
      getTokenTypeName: (index2) => names[parser.getTokenType(index2)],
      getTokenStart: (index2) => parser.getTokenStart(index2),
      getTokenEnd: (index2) => parser.getTokenEnd(index2),
      getTokenValue: (index2) => parser.source.substring(parser.getTokenStart(index2), parser.getTokenEnd(index2)),
      substring: (start, end) => parser.source.substring(start, end),
      balance: parser.balance.subarray(0, parser.tokenCount + 1),
      isBlockOpenerTokenType: parser.isBlockOpenerTokenType,
      isBlockCloserTokenType: parser.isBlockCloserTokenType,
      getBlockTokenPairIndex: (index2) => parser.getBlockTokenPairIndex(index2),
      getLocation: (offset) => locationMap.getLocation(offset, filename),
      getRangeLocation: (start, end) => locationMap.getLocationRange(start, end, filename)
    });
    const parse3 = function(source_, options) {
      source = source_;
      options = options || {};
      parser.setSource(source, index.tokenize);
      locationMap.setSource(source, options.offset, options.line, options.column);
      filename = options.filename || "<unknown>";
      needPositions = Boolean(options.positions);
      onParseError = typeof options.onParseError === "function" ? options.onParseError : NOOP;
      onParseErrorThrow = false;
      parser.parseAtrulePrelude = "parseAtrulePrelude" in options ? Boolean(options.parseAtrulePrelude) : true;
      parser.parseRulePrelude = "parseRulePrelude" in options ? Boolean(options.parseRulePrelude) : true;
      parser.parseValue = "parseValue" in options ? Boolean(options.parseValue) : true;
      parser.parseCustomProperty = "parseCustomProperty" in options ? Boolean(options.parseCustomProperty) : false;
      const { context = "default", list = true, onComment, onToken } = options;
      if (context in parser.context === false) {
        throw new Error("Unknown context `" + context + "`");
      }
      Object.assign(parser, list ? listMethods : arrayMethods);
      if (Array.isArray(onToken)) {
        parser.forEachToken((type, start, end) => {
          onToken.push({ type, start, end });
        });
      } else if (typeof onToken === "function") {
        parser.forEachToken(onToken.bind(createTokenIterateAPI()));
      }
      if (typeof onComment === "function") {
        parser.forEachToken((type, start, end) => {
          if (type === types2.Comment) {
            const loc = parser.getLocation(start, end);
            const value = utils.cmpStr(source, end - 2, end, "*/") ? source.slice(start + 2, end - 2) : source.slice(start + 2, end);
            onComment(value, loc);
          }
        });
      }
      const ast = parser.context[context].call(parser, options);
      if (!parser.eof) {
        parser.error();
      }
      return ast;
    };
    return Object.assign(parse3, {
      SyntaxError: SyntaxError2.SyntaxError,
      config: parser.config
    });
  }
  exports.createParser = createParser;
});

// ../imp-pinned/node_modules/source-map-js/lib/base64.js
var require_base64 = __commonJS((exports) => {
  var intToCharMap = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".split("");
  exports.encode = function(number) {
    if (0 <= number && number < intToCharMap.length) {
      return intToCharMap[number];
    }
    throw new TypeError("Must be between 0 and 63: " + number);
  };
  exports.decode = function(charCode) {
    var bigA = 65;
    var bigZ = 90;
    var littleA = 97;
    var littleZ = 122;
    var zero = 48;
    var nine = 57;
    var plus = 43;
    var slash = 47;
    var littleOffset = 26;
    var numberOffset = 52;
    if (bigA <= charCode && charCode <= bigZ) {
      return charCode - bigA;
    }
    if (littleA <= charCode && charCode <= littleZ) {
      return charCode - littleA + littleOffset;
    }
    if (zero <= charCode && charCode <= nine) {
      return charCode - zero + numberOffset;
    }
    if (charCode == plus) {
      return 62;
    }
    if (charCode == slash) {
      return 63;
    }
    return -1;
  };
});

// ../imp-pinned/node_modules/source-map-js/lib/base64-vlq.js
var require_base64_vlq = __commonJS((exports) => {
  var base64 = require_base64();
  var VLQ_BASE_SHIFT = 5;
  var VLQ_BASE = 1 << VLQ_BASE_SHIFT;
  var VLQ_BASE_MASK = VLQ_BASE - 1;
  var VLQ_CONTINUATION_BIT = VLQ_BASE;
  function toVLQSigned(aValue) {
    return aValue < 0 ? (-aValue << 1) + 1 : (aValue << 1) + 0;
  }
  function fromVLQSigned(aValue) {
    var isNegative = (aValue & 1) === 1;
    var shifted = aValue >> 1;
    return isNegative ? -shifted : shifted;
  }
  exports.encode = function base64VLQ_encode(aValue) {
    var encoded = "";
    var digit;
    var vlq = toVLQSigned(aValue);
    do {
      digit = vlq & VLQ_BASE_MASK;
      vlq >>>= VLQ_BASE_SHIFT;
      if (vlq > 0) {
        digit |= VLQ_CONTINUATION_BIT;
      }
      encoded += base64.encode(digit);
    } while (vlq > 0);
    return encoded;
  };
  exports.decode = function base64VLQ_decode(aStr, aIndex, aOutParam) {
    var strLen = aStr.length;
    var result = 0;
    var shift = 0;
    var continuation, digit;
    do {
      if (aIndex >= strLen) {
        throw new Error("Expected more digits in base 64 VLQ value.");
      }
      digit = base64.decode(aStr.charCodeAt(aIndex++));
      if (digit === -1) {
        throw new Error("Invalid base64 digit: " + aStr.charAt(aIndex - 1));
      }
      continuation = !!(digit & VLQ_CONTINUATION_BIT);
      digit &= VLQ_BASE_MASK;
      result = result + (digit << shift);
      shift += VLQ_BASE_SHIFT;
    } while (continuation);
    aOutParam.value = fromVLQSigned(result);
    aOutParam.rest = aIndex;
  };
});

// ../imp-pinned/node_modules/source-map-js/lib/util.js
var require_util = __commonJS((exports) => {
  function getArg(aArgs, aName, aDefaultValue) {
    if (aName in aArgs) {
      return aArgs[aName];
    } else if (arguments.length === 3) {
      return aDefaultValue;
    } else {
      throw new Error('"' + aName + '" is a required argument.');
    }
  }
  exports.getArg = getArg;
  var urlRegexp = /^(?:([\w+\-.]+):)?\/\/(?:(\w+:\w+)@)?([\w.-]*)(?::(\d+))?(.*)$/;
  var dataUrlRegexp = /^data:.+\,.+$/;
  function urlParse(aUrl) {
    var match = aUrl.match(urlRegexp);
    if (!match) {
      return null;
    }
    return {
      scheme: match[1],
      auth: match[2],
      host: match[3],
      port: match[4],
      path: match[5]
    };
  }
  exports.urlParse = urlParse;
  function urlGenerate(aParsedUrl) {
    var url = "";
    if (aParsedUrl.scheme) {
      url += aParsedUrl.scheme + ":";
    }
    url += "//";
    if (aParsedUrl.auth) {
      url += aParsedUrl.auth + "@";
    }
    if (aParsedUrl.host) {
      url += aParsedUrl.host;
    }
    if (aParsedUrl.port) {
      url += ":" + aParsedUrl.port;
    }
    if (aParsedUrl.path) {
      url += aParsedUrl.path;
    }
    return url;
  }
  exports.urlGenerate = urlGenerate;
  var MAX_CACHED_INPUTS = 32;
  function lruMemoize(f) {
    var cache = [];
    return function(input) {
      for (var i = 0;i < cache.length; i++) {
        if (cache[i].input === input) {
          var temp = cache[0];
          cache[0] = cache[i];
          cache[i] = temp;
          return cache[0].result;
        }
      }
      var result = f(input);
      cache.unshift({
        input,
        result
      });
      if (cache.length > MAX_CACHED_INPUTS) {
        cache.pop();
      }
      return result;
    };
  }
  var normalize = lruMemoize(function normalize2(aPath) {
    var path = aPath;
    var url = urlParse(aPath);
    if (url) {
      if (!url.path) {
        return aPath;
      }
      path = url.path;
    }
    var isAbsolute = exports.isAbsolute(path);
    var parts = [];
    var start = 0;
    var i = 0;
    while (true) {
      start = i;
      i = path.indexOf("/", start);
      if (i === -1) {
        parts.push(path.slice(start));
        break;
      } else {
        parts.push(path.slice(start, i));
        while (i < path.length && path[i] === "/") {
          i++;
        }
      }
    }
    for (var part, up = 0, i = parts.length - 1;i >= 0; i--) {
      part = parts[i];
      if (part === ".") {
        parts.splice(i, 1);
      } else if (part === "..") {
        up++;
      } else if (up > 0) {
        if (part === "") {
          parts.splice(i + 1, up);
          up = 0;
        } else {
          parts.splice(i, 2);
          up--;
        }
      }
    }
    path = parts.join("/");
    if (path === "") {
      path = isAbsolute ? "/" : ".";
    }
    if (url) {
      url.path = path;
      return urlGenerate(url);
    }
    return path;
  });
  exports.normalize = normalize;
  function join(aRoot, aPath) {
    if (aRoot === "") {
      aRoot = ".";
    }
    if (aPath === "") {
      aPath = ".";
    }
    var aPathUrl = urlParse(aPath);
    var aRootUrl = urlParse(aRoot);
    if (aRootUrl) {
      aRoot = aRootUrl.path || "/";
    }
    if (aPathUrl && !aPathUrl.scheme) {
      if (aRootUrl) {
        aPathUrl.scheme = aRootUrl.scheme;
      }
      return urlGenerate(aPathUrl);
    }
    if (aPathUrl || aPath.match(dataUrlRegexp)) {
      return aPath;
    }
    if (aRootUrl && !aRootUrl.host && !aRootUrl.path) {
      aRootUrl.host = aPath;
      return urlGenerate(aRootUrl);
    }
    var joined = aPath.charAt(0) === "/" ? aPath : normalize(aRoot.replace(/\/+$/, "") + "/" + aPath);
    if (aRootUrl) {
      aRootUrl.path = joined;
      return urlGenerate(aRootUrl);
    }
    return joined;
  }
  exports.join = join;
  exports.isAbsolute = function(aPath) {
    return aPath.charAt(0) === "/" || urlRegexp.test(aPath);
  };
  function relative(aRoot, aPath) {
    if (aRoot === "") {
      aRoot = ".";
    }
    aRoot = aRoot.replace(/\/$/, "");
    var level = 0;
    while (aPath.indexOf(aRoot + "/") !== 0) {
      var index = aRoot.lastIndexOf("/");
      if (index < 0) {
        return aPath;
      }
      aRoot = aRoot.slice(0, index);
      if (aRoot.match(/^([^\/]+:\/)?\/*$/)) {
        return aPath;
      }
      ++level;
    }
    return Array(level + 1).join("../") + aPath.substr(aRoot.length + 1);
  }
  exports.relative = relative;
  var supportsNullProto = function() {
    var obj = Object.create(null);
    return !("__proto__" in obj);
  }();
  function identity(s) {
    return s;
  }
  function toSetString(aStr) {
    if (isProtoString(aStr)) {
      return "$" + aStr;
    }
    return aStr;
  }
  exports.toSetString = supportsNullProto ? identity : toSetString;
  function fromSetString(aStr) {
    if (isProtoString(aStr)) {
      return aStr.slice(1);
    }
    return aStr;
  }
  exports.fromSetString = supportsNullProto ? identity : fromSetString;
  function isProtoString(s) {
    if (!s) {
      return false;
    }
    var length = s.length;
    if (length < 9) {
      return false;
    }
    if (s.charCodeAt(length - 1) !== 95 || s.charCodeAt(length - 2) !== 95 || s.charCodeAt(length - 3) !== 111 || s.charCodeAt(length - 4) !== 116 || s.charCodeAt(length - 5) !== 111 || s.charCodeAt(length - 6) !== 114 || s.charCodeAt(length - 7) !== 112 || s.charCodeAt(length - 8) !== 95 || s.charCodeAt(length - 9) !== 95) {
      return false;
    }
    for (var i = length - 10;i >= 0; i--) {
      if (s.charCodeAt(i) !== 36) {
        return false;
      }
    }
    return true;
  }
  function compareByOriginalPositions(mappingA, mappingB, onlyCompareOriginal) {
    var cmp = strcmp(mappingA.source, mappingB.source);
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalLine - mappingB.originalLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalColumn - mappingB.originalColumn;
    if (cmp !== 0 || onlyCompareOriginal) {
      return cmp;
    }
    cmp = mappingA.generatedColumn - mappingB.generatedColumn;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.generatedLine - mappingB.generatedLine;
    if (cmp !== 0) {
      return cmp;
    }
    return strcmp(mappingA.name, mappingB.name);
  }
  exports.compareByOriginalPositions = compareByOriginalPositions;
  function compareByOriginalPositionsNoSource(mappingA, mappingB, onlyCompareOriginal) {
    var cmp;
    cmp = mappingA.originalLine - mappingB.originalLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalColumn - mappingB.originalColumn;
    if (cmp !== 0 || onlyCompareOriginal) {
      return cmp;
    }
    cmp = mappingA.generatedColumn - mappingB.generatedColumn;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.generatedLine - mappingB.generatedLine;
    if (cmp !== 0) {
      return cmp;
    }
    return strcmp(mappingA.name, mappingB.name);
  }
  exports.compareByOriginalPositionsNoSource = compareByOriginalPositionsNoSource;
  function compareByGeneratedPositionsDeflated(mappingA, mappingB, onlyCompareGenerated) {
    var cmp = mappingA.generatedLine - mappingB.generatedLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.generatedColumn - mappingB.generatedColumn;
    if (cmp !== 0 || onlyCompareGenerated) {
      return cmp;
    }
    cmp = strcmp(mappingA.source, mappingB.source);
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalLine - mappingB.originalLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalColumn - mappingB.originalColumn;
    if (cmp !== 0) {
      return cmp;
    }
    return strcmp(mappingA.name, mappingB.name);
  }
  exports.compareByGeneratedPositionsDeflated = compareByGeneratedPositionsDeflated;
  function compareByGeneratedPositionsDeflatedNoLine(mappingA, mappingB, onlyCompareGenerated) {
    var cmp = mappingA.generatedColumn - mappingB.generatedColumn;
    if (cmp !== 0 || onlyCompareGenerated) {
      return cmp;
    }
    cmp = strcmp(mappingA.source, mappingB.source);
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalLine - mappingB.originalLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalColumn - mappingB.originalColumn;
    if (cmp !== 0) {
      return cmp;
    }
    return strcmp(mappingA.name, mappingB.name);
  }
  exports.compareByGeneratedPositionsDeflatedNoLine = compareByGeneratedPositionsDeflatedNoLine;
  function strcmp(aStr1, aStr2) {
    if (aStr1 === aStr2) {
      return 0;
    }
    if (aStr1 === null) {
      return 1;
    }
    if (aStr2 === null) {
      return -1;
    }
    if (aStr1 > aStr2) {
      return 1;
    }
    return -1;
  }
  function compareByGeneratedPositionsInflated(mappingA, mappingB) {
    var cmp = mappingA.generatedLine - mappingB.generatedLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.generatedColumn - mappingB.generatedColumn;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = strcmp(mappingA.source, mappingB.source);
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalLine - mappingB.originalLine;
    if (cmp !== 0) {
      return cmp;
    }
    cmp = mappingA.originalColumn - mappingB.originalColumn;
    if (cmp !== 0) {
      return cmp;
    }
    return strcmp(mappingA.name, mappingB.name);
  }
  exports.compareByGeneratedPositionsInflated = compareByGeneratedPositionsInflated;
  function parseSourceMapInput(str) {
    return JSON.parse(str.replace(/^\)]}'[^\n]*\n/, ""));
  }
  exports.parseSourceMapInput = parseSourceMapInput;
  function computeSourceURL(sourceRoot, sourceURL, sourceMapURL) {
    sourceURL = sourceURL || "";
    if (sourceRoot) {
      if (sourceRoot[sourceRoot.length - 1] !== "/" && sourceURL[0] !== "/") {
        sourceRoot += "/";
      }
      sourceURL = sourceRoot + sourceURL;
    }
    if (sourceMapURL) {
      var parsed = urlParse(sourceMapURL);
      if (!parsed) {
        throw new Error("sourceMapURL could not be parsed");
      }
      if (parsed.path) {
        var index = parsed.path.lastIndexOf("/");
        if (index >= 0) {
          parsed.path = parsed.path.substring(0, index + 1);
        }
      }
      sourceURL = join(urlGenerate(parsed), sourceURL);
    }
    return normalize(sourceURL);
  }
  exports.computeSourceURL = computeSourceURL;
});

// ../imp-pinned/node_modules/source-map-js/lib/array-set.js
var require_array_set = __commonJS((exports) => {
  var util = require_util();
  var has = Object.prototype.hasOwnProperty;
  var hasNativeMap = typeof Map !== "undefined";
  function ArraySet() {
    this._array = [];
    this._set = hasNativeMap ? new Map : Object.create(null);
  }
  ArraySet.fromArray = function ArraySet_fromArray(aArray, aAllowDuplicates) {
    var set = new ArraySet;
    for (var i = 0, len = aArray.length;i < len; i++) {
      set.add(aArray[i], aAllowDuplicates);
    }
    return set;
  };
  ArraySet.prototype.size = function ArraySet_size() {
    return hasNativeMap ? this._set.size : Object.getOwnPropertyNames(this._set).length;
  };
  ArraySet.prototype.add = function ArraySet_add(aStr, aAllowDuplicates) {
    var sStr = hasNativeMap ? aStr : util.toSetString(aStr);
    var isDuplicate = hasNativeMap ? this.has(aStr) : has.call(this._set, sStr);
    var idx = this._array.length;
    if (!isDuplicate || aAllowDuplicates) {
      this._array.push(aStr);
    }
    if (!isDuplicate) {
      if (hasNativeMap) {
        this._set.set(aStr, idx);
      } else {
        this._set[sStr] = idx;
      }
    }
  };
  ArraySet.prototype.has = function ArraySet_has(aStr) {
    if (hasNativeMap) {
      return this._set.has(aStr);
    } else {
      var sStr = util.toSetString(aStr);
      return has.call(this._set, sStr);
    }
  };
  ArraySet.prototype.indexOf = function ArraySet_indexOf(aStr) {
    if (hasNativeMap) {
      var idx = this._set.get(aStr);
      if (idx >= 0) {
        return idx;
      }
    } else {
      var sStr = util.toSetString(aStr);
      if (has.call(this._set, sStr)) {
        return this._set[sStr];
      }
    }
    throw new Error('"' + aStr + '" is not in the set.');
  };
  ArraySet.prototype.at = function ArraySet_at(aIdx) {
    if (aIdx >= 0 && aIdx < this._array.length) {
      return this._array[aIdx];
    }
    throw new Error("No element indexed by " + aIdx);
  };
  ArraySet.prototype.toArray = function ArraySet_toArray() {
    return this._array.slice();
  };
  exports.ArraySet = ArraySet;
});

// ../imp-pinned/node_modules/source-map-js/lib/mapping-list.js
var require_mapping_list = __commonJS((exports) => {
  var util = require_util();
  function generatedPositionAfter(mappingA, mappingB) {
    var lineA = mappingA.generatedLine;
    var lineB = mappingB.generatedLine;
    var columnA = mappingA.generatedColumn;
    var columnB = mappingB.generatedColumn;
    return lineB > lineA || lineB == lineA && columnB >= columnA || util.compareByGeneratedPositionsInflated(mappingA, mappingB) <= 0;
  }
  function MappingList() {
    this._array = [];
    this._sorted = true;
    this._last = { generatedLine: -1, generatedColumn: 0 };
  }
  MappingList.prototype.unsortedForEach = function MappingList_forEach(aCallback, aThisArg) {
    this._array.forEach(aCallback, aThisArg);
  };
  MappingList.prototype.add = function MappingList_add(aMapping) {
    if (generatedPositionAfter(this._last, aMapping)) {
      this._last = aMapping;
      this._array.push(aMapping);
    } else {
      this._sorted = false;
      this._array.push(aMapping);
    }
  };
  MappingList.prototype.toArray = function MappingList_toArray() {
    if (!this._sorted) {
      this._array.sort(util.compareByGeneratedPositionsInflated);
      this._sorted = true;
    }
    return this._array;
  };
  exports.MappingList = MappingList;
});

// ../imp-pinned/node_modules/source-map-js/lib/source-map-generator.js
var require_source_map_generator = __commonJS((exports) => {
  var base64VLQ = require_base64_vlq();
  var util = require_util();
  var ArraySet = require_array_set().ArraySet;
  var MappingList = require_mapping_list().MappingList;
  function SourceMapGenerator(aArgs) {
    if (!aArgs) {
      aArgs = {};
    }
    this._file = util.getArg(aArgs, "file", null);
    this._sourceRoot = util.getArg(aArgs, "sourceRoot", null);
    this._skipValidation = util.getArg(aArgs, "skipValidation", false);
    this._ignoreInvalidMapping = util.getArg(aArgs, "ignoreInvalidMapping", false);
    this._sources = new ArraySet;
    this._names = new ArraySet;
    this._mappings = new MappingList;
    this._sourcesContents = null;
  }
  SourceMapGenerator.prototype._version = 3;
  SourceMapGenerator.fromSourceMap = function SourceMapGenerator_fromSourceMap(aSourceMapConsumer, generatorOps) {
    var sourceRoot = aSourceMapConsumer.sourceRoot;
    var generator = new SourceMapGenerator(Object.assign(generatorOps || {}, {
      file: aSourceMapConsumer.file,
      sourceRoot
    }));
    aSourceMapConsumer.eachMapping(function(mapping) {
      var newMapping = {
        generated: {
          line: mapping.generatedLine,
          column: mapping.generatedColumn
        }
      };
      if (mapping.source != null) {
        newMapping.source = mapping.source;
        if (sourceRoot != null) {
          newMapping.source = util.relative(sourceRoot, newMapping.source);
        }
        newMapping.original = {
          line: mapping.originalLine,
          column: mapping.originalColumn
        };
        if (mapping.name != null) {
          newMapping.name = mapping.name;
        }
      }
      generator.addMapping(newMapping);
    });
    aSourceMapConsumer.sources.forEach(function(sourceFile) {
      var sourceRelative = sourceFile;
      if (sourceRoot !== null) {
        sourceRelative = util.relative(sourceRoot, sourceFile);
      }
      if (!generator._sources.has(sourceRelative)) {
        generator._sources.add(sourceRelative);
      }
      var content = aSourceMapConsumer.sourceContentFor(sourceFile);
      if (content != null) {
        generator.setSourceContent(sourceFile, content);
      }
    });
    return generator;
  };
  SourceMapGenerator.prototype.addMapping = function SourceMapGenerator_addMapping(aArgs) {
    var generated = util.getArg(aArgs, "generated");
    var original = util.getArg(aArgs, "original", null);
    var source = util.getArg(aArgs, "source", null);
    var name = util.getArg(aArgs, "name", null);
    if (!this._skipValidation) {
      if (this._validateMapping(generated, original, source, name) === false) {
        return;
      }
    }
    if (source != null) {
      source = String(source);
      if (!this._sources.has(source)) {
        this._sources.add(source);
      }
    }
    if (name != null) {
      name = String(name);
      if (!this._names.has(name)) {
        this._names.add(name);
      }
    }
    this._mappings.add({
      generatedLine: generated.line,
      generatedColumn: generated.column,
      originalLine: original != null && original.line,
      originalColumn: original != null && original.column,
      source,
      name
    });
  };
  SourceMapGenerator.prototype.setSourceContent = function SourceMapGenerator_setSourceContent(aSourceFile, aSourceContent) {
    var source = aSourceFile;
    if (this._sourceRoot != null) {
      source = util.relative(this._sourceRoot, source);
    }
    if (aSourceContent != null) {
      if (!this._sourcesContents) {
        this._sourcesContents = Object.create(null);
      }
      this._sourcesContents[util.toSetString(source)] = aSourceContent;
    } else if (this._sourcesContents) {
      delete this._sourcesContents[util.toSetString(source)];
      if (Object.keys(this._sourcesContents).length === 0) {
        this._sourcesContents = null;
      }
    }
  };
  SourceMapGenerator.prototype.applySourceMap = function SourceMapGenerator_applySourceMap(aSourceMapConsumer, aSourceFile, aSourceMapPath) {
    var sourceFile = aSourceFile;
    if (aSourceFile == null) {
      if (aSourceMapConsumer.file == null) {
        throw new Error("SourceMapGenerator.prototype.applySourceMap requires either an explicit source file, " + `or the source map's "file" property. Both were omitted.`);
      }
      sourceFile = aSourceMapConsumer.file;
    }
    var sourceRoot = this._sourceRoot;
    if (sourceRoot != null) {
      sourceFile = util.relative(sourceRoot, sourceFile);
    }
    var newSources = new ArraySet;
    var newNames = new ArraySet;
    this._mappings.unsortedForEach(function(mapping) {
      if (mapping.source === sourceFile && mapping.originalLine != null) {
        var original = aSourceMapConsumer.originalPositionFor({
          line: mapping.originalLine,
          column: mapping.originalColumn
        });
        if (original.source != null) {
          mapping.source = original.source;
          if (aSourceMapPath != null) {
            mapping.source = util.join(aSourceMapPath, mapping.source);
          }
          if (sourceRoot != null) {
            mapping.source = util.relative(sourceRoot, mapping.source);
          }
          mapping.originalLine = original.line;
          mapping.originalColumn = original.column;
          if (original.name != null) {
            mapping.name = original.name;
          }
        }
      }
      var source = mapping.source;
      if (source != null && !newSources.has(source)) {
        newSources.add(source);
      }
      var name = mapping.name;
      if (name != null && !newNames.has(name)) {
        newNames.add(name);
      }
    }, this);
    this._sources = newSources;
    this._names = newNames;
    aSourceMapConsumer.sources.forEach(function(sourceFile2) {
      var content = aSourceMapConsumer.sourceContentFor(sourceFile2);
      if (content != null) {
        if (aSourceMapPath != null) {
          sourceFile2 = util.join(aSourceMapPath, sourceFile2);
        }
        if (sourceRoot != null) {
          sourceFile2 = util.relative(sourceRoot, sourceFile2);
        }
        this.setSourceContent(sourceFile2, content);
      }
    }, this);
  };
  SourceMapGenerator.prototype._validateMapping = function SourceMapGenerator_validateMapping(aGenerated, aOriginal, aSource, aName) {
    if (aOriginal && typeof aOriginal.line !== "number" && typeof aOriginal.column !== "number") {
      var message = "original.line and original.column are not numbers -- you probably meant to omit " + "the original mapping entirely and only map the generated position. If so, pass " + "null for the original mapping instead of an object with empty or null values.";
      if (this._ignoreInvalidMapping) {
        if (typeof console !== "undefined" && console.warn) {
          console.warn(message);
        }
        return false;
      } else {
        throw new Error(message);
      }
    }
    if (aGenerated && "line" in aGenerated && "column" in aGenerated && aGenerated.line > 0 && aGenerated.column >= 0 && !aOriginal && !aSource && !aName) {
      return;
    } else if (aGenerated && "line" in aGenerated && "column" in aGenerated && aOriginal && "line" in aOriginal && "column" in aOriginal && aGenerated.line > 0 && aGenerated.column >= 0 && aOriginal.line > 0 && aOriginal.column >= 0 && aSource) {
      return;
    } else {
      var message = "Invalid mapping: " + JSON.stringify({
        generated: aGenerated,
        source: aSource,
        original: aOriginal,
        name: aName
      });
      if (this._ignoreInvalidMapping) {
        if (typeof console !== "undefined" && console.warn) {
          console.warn(message);
        }
        return false;
      } else {
        throw new Error(message);
      }
    }
  };
  SourceMapGenerator.prototype._serializeMappings = function SourceMapGenerator_serializeMappings() {
    var previousGeneratedColumn = 0;
    var previousGeneratedLine = 1;
    var previousOriginalColumn = 0;
    var previousOriginalLine = 0;
    var previousName = 0;
    var previousSource = 0;
    var result = "";
    var next;
    var mapping;
    var nameIdx;
    var sourceIdx;
    var mappings = this._mappings.toArray();
    for (var i = 0, len = mappings.length;i < len; i++) {
      mapping = mappings[i];
      next = "";
      if (mapping.generatedLine !== previousGeneratedLine) {
        previousGeneratedColumn = 0;
        while (mapping.generatedLine !== previousGeneratedLine) {
          next += ";";
          previousGeneratedLine++;
        }
      } else {
        if (i > 0) {
          if (!util.compareByGeneratedPositionsInflated(mapping, mappings[i - 1])) {
            continue;
          }
          next += ",";
        }
      }
      next += base64VLQ.encode(mapping.generatedColumn - previousGeneratedColumn);
      previousGeneratedColumn = mapping.generatedColumn;
      if (mapping.source != null) {
        sourceIdx = this._sources.indexOf(mapping.source);
        next += base64VLQ.encode(sourceIdx - previousSource);
        previousSource = sourceIdx;
        next += base64VLQ.encode(mapping.originalLine - 1 - previousOriginalLine);
        previousOriginalLine = mapping.originalLine - 1;
        next += base64VLQ.encode(mapping.originalColumn - previousOriginalColumn);
        previousOriginalColumn = mapping.originalColumn;
        if (mapping.name != null) {
          nameIdx = this._names.indexOf(mapping.name);
          next += base64VLQ.encode(nameIdx - previousName);
          previousName = nameIdx;
        }
      }
      result += next;
    }
    return result;
  };
  SourceMapGenerator.prototype._generateSourcesContent = function SourceMapGenerator_generateSourcesContent(aSources, aSourceRoot) {
    return aSources.map(function(source) {
      if (!this._sourcesContents) {
        return null;
      }
      if (aSourceRoot != null) {
        source = util.relative(aSourceRoot, source);
      }
      var key = util.toSetString(source);
      return Object.prototype.hasOwnProperty.call(this._sourcesContents, key) ? this._sourcesContents[key] : null;
    }, this);
  };
  SourceMapGenerator.prototype.toJSON = function SourceMapGenerator_toJSON() {
    var map = {
      version: this._version,
      sources: this._sources.toArray(),
      names: this._names.toArray(),
      mappings: this._serializeMappings()
    };
    if (this._file != null) {
      map.file = this._file;
    }
    if (this._sourceRoot != null) {
      map.sourceRoot = this._sourceRoot;
    }
    if (this._sourcesContents) {
      map.sourcesContent = this._generateSourcesContent(map.sources, map.sourceRoot);
    }
    return map;
  };
  SourceMapGenerator.prototype.toString = function SourceMapGenerator_toString() {
    return JSON.stringify(this.toJSON());
  };
  exports.SourceMapGenerator = SourceMapGenerator;
});

// ../imp-pinned/node_modules/css-tree/cjs/generator/sourceMap.cjs
var require_sourceMap = __commonJS((exports) => {
  var sourceMapGenerator_js = require_source_map_generator();
  var trackNodes = new Set(["Atrule", "Selector", "Declaration"]);
  function generateSourceMap(handlers) {
    const map = new sourceMapGenerator_js.SourceMapGenerator;
    const generated = {
      line: 1,
      column: 0
    };
    const original = {
      line: 0,
      column: 0
    };
    const activatedGenerated = {
      line: 1,
      column: 0
    };
    const activatedMapping = {
      generated: activatedGenerated
    };
    let line = 1;
    let column = 0;
    let sourceMappingActive = false;
    const origHandlersNode = handlers.node;
    handlers.node = function(node2) {
      if (node2.loc && node2.loc.start && trackNodes.has(node2.type)) {
        const nodeLine = node2.loc.start.line;
        const nodeColumn = node2.loc.start.column - 1;
        if (original.line !== nodeLine || original.column !== nodeColumn) {
          original.line = nodeLine;
          original.column = nodeColumn;
          generated.line = line;
          generated.column = column;
          if (sourceMappingActive) {
            sourceMappingActive = false;
            if (generated.line !== activatedGenerated.line || generated.column !== activatedGenerated.column) {
              map.addMapping(activatedMapping);
            }
          }
          sourceMappingActive = true;
          map.addMapping({
            source: node2.loc.source,
            original,
            generated
          });
        }
      }
      origHandlersNode.call(this, node2);
      if (sourceMappingActive && trackNodes.has(node2.type)) {
        activatedGenerated.line = line;
        activatedGenerated.column = column;
      }
    };
    const origHandlersEmit = handlers.emit;
    handlers.emit = function(value, type, auto) {
      for (let i = 0;i < value.length; i++) {
        if (value.charCodeAt(i) === 10) {
          line++;
          column = 0;
        } else {
          column++;
        }
      }
      origHandlersEmit(value, type, auto);
    };
    const origHandlersResult = handlers.result;
    handlers.result = function() {
      if (sourceMappingActive) {
        map.addMapping(activatedMapping);
      }
      return {
        css: origHandlersResult(),
        map
      };
    };
    return handlers;
  }
  exports.generateSourceMap = generateSourceMap;
});

// ../imp-pinned/node_modules/css-tree/cjs/generator/token-before.cjs
var require_token_before = __commonJS((exports) => {
  var types2 = require_types();
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var code = (type, value) => {
    if (type === types2.Delim) {
      type = value;
    }
    if (typeof type === "string") {
      type = Math.min(type.charCodeAt(0), 128) << 6;
    }
    return type << 1;
  };
  var specPairs = [
    [types2.Ident, types2.Ident],
    [types2.Ident, types2.Function],
    [types2.Ident, types2.Url],
    [types2.Ident, types2.BadUrl],
    [types2.Ident, "-"],
    [types2.Ident, types2.Number],
    [types2.Ident, types2.Percentage],
    [types2.Ident, types2.Dimension],
    [types2.Ident, types2.CDC],
    [types2.Ident, types2.LeftParenthesis],
    [types2.AtKeyword, types2.Ident],
    [types2.AtKeyword, types2.Function],
    [types2.AtKeyword, types2.Url],
    [types2.AtKeyword, types2.BadUrl],
    [types2.AtKeyword, "-"],
    [types2.AtKeyword, types2.Number],
    [types2.AtKeyword, types2.Percentage],
    [types2.AtKeyword, types2.Dimension],
    [types2.AtKeyword, types2.CDC],
    [types2.Hash, types2.Ident],
    [types2.Hash, types2.Function],
    [types2.Hash, types2.Url],
    [types2.Hash, types2.BadUrl],
    [types2.Hash, "-"],
    [types2.Hash, types2.Number],
    [types2.Hash, types2.Percentage],
    [types2.Hash, types2.Dimension],
    [types2.Hash, types2.CDC],
    [types2.Dimension, types2.Ident],
    [types2.Dimension, types2.Function],
    [types2.Dimension, types2.Url],
    [types2.Dimension, types2.BadUrl],
    [types2.Dimension, "-"],
    [types2.Dimension, types2.Number],
    [types2.Dimension, types2.Percentage],
    [types2.Dimension, types2.Dimension],
    [types2.Dimension, types2.CDC],
    ["#", types2.Ident],
    ["#", types2.Function],
    ["#", types2.Url],
    ["#", types2.BadUrl],
    ["#", "-"],
    ["#", types2.Number],
    ["#", types2.Percentage],
    ["#", types2.Dimension],
    ["#", types2.CDC],
    ["-", types2.Ident],
    ["-", types2.Function],
    ["-", types2.Url],
    ["-", types2.BadUrl],
    ["-", "-"],
    ["-", types2.Number],
    ["-", types2.Percentage],
    ["-", types2.Dimension],
    ["-", types2.CDC],
    [types2.Number, types2.Ident],
    [types2.Number, types2.Function],
    [types2.Number, types2.Url],
    [types2.Number, types2.BadUrl],
    [types2.Number, types2.Number],
    [types2.Number, types2.Percentage],
    [types2.Number, types2.Dimension],
    [types2.Number, "%"],
    [types2.Number, types2.CDC],
    ["@", types2.Ident],
    ["@", types2.Function],
    ["@", types2.Url],
    ["@", types2.BadUrl],
    ["@", "-"],
    ["@", types2.CDC],
    [".", types2.Number],
    [".", types2.Percentage],
    [".", types2.Dimension],
    ["+", types2.Number],
    ["+", types2.Percentage],
    ["+", types2.Dimension],
    ["/", "*"]
  ];
  var safePairs = specPairs.concat([
    [types2.Ident, types2.Hash],
    [types2.Dimension, types2.Hash],
    [types2.Hash, types2.Hash],
    [types2.AtKeyword, types2.LeftParenthesis],
    [types2.AtKeyword, types2.String],
    [types2.AtKeyword, types2.Colon],
    [types2.Percentage, types2.Percentage],
    [types2.Percentage, types2.Dimension],
    [types2.Percentage, types2.Function],
    [types2.Percentage, "-"],
    [types2.RightParenthesis, types2.Ident],
    [types2.RightParenthesis, types2.Function],
    [types2.RightParenthesis, types2.Percentage],
    [types2.RightParenthesis, types2.Dimension],
    [types2.RightParenthesis, types2.Hash],
    [types2.RightParenthesis, "-"]
  ]);
  function createMap(pairs) {
    const isWhiteSpaceRequired = new Set(pairs.map(([prev, next]) => code(prev) << 16 | code(next)));
    return function(prevCode, type, value) {
      const nextCode = code(type, value);
      const nextCharCode = value.charCodeAt(0);
      const emitWs = nextCharCode === HYPHENMINUS && type !== types2.Ident && type !== types2.Function && type !== types2.CDC || nextCharCode === PLUSSIGN ? isWhiteSpaceRequired.has((prevCode & 65534) << 16 | nextCharCode << 7) : isWhiteSpaceRequired.has((prevCode & 65534) << 16 | nextCode);
      return nextCode | emitWs;
    };
  }
  var spec = createMap(specPairs);
  var safe = createMap(safePairs);
  exports.safe = safe;
  exports.spec = spec;
});

// ../imp-pinned/node_modules/css-tree/cjs/generator/create.cjs
var require_create2 = __commonJS((exports) => {
  var index = require_tokenizer();
  var sourceMap = require_sourceMap();
  var tokenBefore = require_token_before();
  var types2 = require_types();
  var REVERSESOLIDUS = 92;
  function processChildren(node2, delimeter) {
    if (typeof delimeter === "function") {
      let prev = null;
      node2.children.forEach((node3) => {
        if (prev !== null) {
          delimeter.call(this, prev);
        }
        this.node(node3);
        prev = node3;
      });
      return;
    }
    node2.children.forEach(this.node, this);
  }
  function createGenerator(config) {
    const types$1 = new Map;
    for (let [name, item] of Object.entries(config.node)) {
      const fn = item.generate || item;
      if (typeof fn === "function") {
        types$1.set(name, item.generate || item);
      }
    }
    return function(node2, options) {
      let buffer = "";
      let prevCode = 0;
      let handlers = {
        node(node3) {
          if (types$1.has(node3.type)) {
            types$1.get(node3.type).call(publicApi, node3);
          } else {
            throw new Error("Unknown node type: " + node3.type);
          }
        },
        tokenBefore: tokenBefore.safe,
        token(type, value, suppressAutoWhiteSpace) {
          prevCode = this.tokenBefore(prevCode, type, value);
          if (!suppressAutoWhiteSpace && prevCode & 1) {
            this.emit(" ", types2.WhiteSpace, true);
          }
          this.emit(value, type, false);
          if (type === types2.Delim && value.charCodeAt(0) === REVERSESOLIDUS) {
            this.emit(`
`, types2.WhiteSpace, true);
          }
        },
        emit(value) {
          buffer += value;
        },
        result() {
          return buffer;
        }
      };
      if (options) {
        if (typeof options.decorator === "function") {
          handlers = options.decorator(handlers);
        }
        if (options.sourceMap) {
          handlers = sourceMap.generateSourceMap(handlers);
        }
        if (options.mode in tokenBefore) {
          handlers.tokenBefore = tokenBefore[options.mode];
        }
      }
      const publicApi = {
        node: (node3) => handlers.node(node3),
        children: processChildren,
        token: (type, value) => handlers.token(type, value),
        tokenize: (raw) => index.tokenize(raw, (type, start, end) => {
          handlers.token(type, raw.slice(start, end), start !== 0);
        })
      };
      handlers.node(node2);
      return handlers.result();
    };
  }
  exports.createGenerator = createGenerator;
});

// ../imp-pinned/node_modules/css-tree/cjs/convertor/create.cjs
var require_create3 = __commonJS((exports) => {
  var List = require_List();
  function createConvertor(walk) {
    return {
      fromPlainObject(ast) {
        walk(ast, {
          enter(node2) {
            if (node2.children && node2.children instanceof List.List === false) {
              node2.children = new List.List().fromArray(node2.children);
            }
          }
        });
        return ast;
      },
      toPlainObject(ast) {
        walk(ast, {
          leave(node2) {
            if (node2.children && node2.children instanceof List.List) {
              node2.children = node2.children.toArray();
            }
          }
        });
        return ast;
      }
    };
  }
  exports.createConvertor = createConvertor;
});

// ../imp-pinned/node_modules/css-tree/cjs/walker/create.cjs
var require_create4 = __commonJS((exports) => {
  var { hasOwnProperty: hasOwnProperty2 } = Object.prototype;
  var noop = function() {};
  function ensureFunction(value) {
    return typeof value === "function" ? value : noop;
  }
  function invokeForType(fn, type) {
    return function(node2, item, list) {
      if (node2.type === type) {
        fn.call(this, node2, item, list);
      }
    };
  }
  function getWalkersFromStructure(name, nodeType) {
    const structure = nodeType.structure;
    const walkers = [];
    for (const key in structure) {
      if (hasOwnProperty2.call(structure, key) === false) {
        continue;
      }
      let fieldTypes = structure[key];
      const walker = {
        name: key,
        type: false,
        nullable: false
      };
      if (!Array.isArray(fieldTypes)) {
        fieldTypes = [fieldTypes];
      }
      for (const fieldType of fieldTypes) {
        if (fieldType === null) {
          walker.nullable = true;
        } else if (typeof fieldType === "string") {
          walker.type = "node";
        } else if (Array.isArray(fieldType)) {
          walker.type = "list";
        }
      }
      if (walker.type) {
        walkers.push(walker);
      }
    }
    if (walkers.length) {
      return {
        context: nodeType.walkContext,
        fields: walkers
      };
    }
    return null;
  }
  function getTypesFromConfig(config) {
    const types2 = {};
    for (const name in config.node) {
      if (hasOwnProperty2.call(config.node, name)) {
        const nodeType = config.node[name];
        if (!nodeType.structure) {
          throw new Error("Missed `structure` field in `" + name + "` node type definition");
        }
        types2[name] = getWalkersFromStructure(name, nodeType);
      }
    }
    return types2;
  }
  function createTypeIterator(config, reverse) {
    const fields = config.fields.slice();
    const contextName = config.context;
    const useContext = typeof contextName === "string";
    if (reverse) {
      fields.reverse();
    }
    return function(node2, context, walk, walkReducer) {
      let prevContextValue;
      if (useContext) {
        prevContextValue = context[contextName];
        context[contextName] = node2;
      }
      for (const field of fields) {
        const ref = node2[field.name];
        if (!field.nullable || ref) {
          if (field.type === "list") {
            const breakWalk = reverse ? ref.reduceRight(walkReducer, false) : ref.reduce(walkReducer, false);
            if (breakWalk) {
              return true;
            }
          } else if (walk(ref)) {
            return true;
          }
        }
      }
      if (useContext) {
        context[contextName] = prevContextValue;
      }
    };
  }
  function createFastTraveralMap({
    StyleSheet,
    Atrule,
    Rule,
    Block,
    DeclarationList
  }) {
    return {
      Atrule: {
        StyleSheet,
        Atrule,
        Rule,
        Block
      },
      Rule: {
        StyleSheet,
        Atrule,
        Rule,
        Block
      },
      Declaration: {
        StyleSheet,
        Atrule,
        Rule,
        Block,
        DeclarationList
      }
    };
  }
  function createWalker(config) {
    const types2 = getTypesFromConfig(config);
    const iteratorsNatural = {};
    const iteratorsReverse = {};
    const breakWalk = Symbol("break-walk");
    const skipNode = Symbol("skip-node");
    for (const name in types2) {
      if (hasOwnProperty2.call(types2, name) && types2[name] !== null) {
        iteratorsNatural[name] = createTypeIterator(types2[name], false);
        iteratorsReverse[name] = createTypeIterator(types2[name], true);
      }
    }
    const fastTraversalIteratorsNatural = createFastTraveralMap(iteratorsNatural);
    const fastTraversalIteratorsReverse = createFastTraveralMap(iteratorsReverse);
    const walk = function(root, options) {
      function walkNode(node2, item, list) {
        const enterRet = enter.call(context, node2, item, list);
        if (enterRet === breakWalk) {
          return true;
        }
        if (enterRet === skipNode) {
          return false;
        }
        if (iterators.hasOwnProperty(node2.type)) {
          if (iterators[node2.type](node2, context, walkNode, walkReducer)) {
            return true;
          }
        }
        if (leave.call(context, node2, item, list) === breakWalk) {
          return true;
        }
        return false;
      }
      let enter = noop;
      let leave = noop;
      let iterators = iteratorsNatural;
      let walkReducer = (ret, data, item, list) => ret || walkNode(data, item, list);
      const context = {
        break: breakWalk,
        skip: skipNode,
        root,
        stylesheet: null,
        atrule: null,
        atrulePrelude: null,
        rule: null,
        selector: null,
        block: null,
        declaration: null,
        function: null
      };
      if (typeof options === "function") {
        enter = options;
      } else if (options) {
        enter = ensureFunction(options.enter);
        leave = ensureFunction(options.leave);
        if (options.reverse) {
          iterators = iteratorsReverse;
        }
        if (options.visit) {
          if (fastTraversalIteratorsNatural.hasOwnProperty(options.visit)) {
            iterators = options.reverse ? fastTraversalIteratorsReverse[options.visit] : fastTraversalIteratorsNatural[options.visit];
          } else if (!types2.hasOwnProperty(options.visit)) {
            throw new Error("Bad value `" + options.visit + "` for `visit` option (should be: " + Object.keys(types2).sort().join(", ") + ")");
          }
          enter = invokeForType(enter, options.visit);
          leave = invokeForType(leave, options.visit);
        }
      }
      if (enter === noop && leave === noop) {
        throw new Error("Neither `enter` nor `leave` walker handler is set or both aren't a function");
      }
      walkNode(root);
    };
    walk.break = breakWalk;
    walk.skip = skipNode;
    walk.find = function(ast, fn) {
      let found = null;
      walk(ast, function(node2, item, list) {
        if (fn.call(this, node2, item, list)) {
          found = node2;
          return breakWalk;
        }
      });
      return found;
    };
    walk.findLast = function(ast, fn) {
      let found = null;
      walk(ast, {
        reverse: true,
        enter(node2, item, list) {
          if (fn.call(this, node2, item, list)) {
            found = node2;
            return breakWalk;
          }
        }
      });
      return found;
    };
    walk.findAll = function(ast, fn) {
      const found = [];
      walk(ast, function(node2, item, list) {
        if (fn.call(this, node2, item, list)) {
          found.push(node2);
        }
      });
      return found;
    };
    return walk;
  }
  exports.createWalker = createWalker;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/generate.cjs
var require_generate = __commonJS((exports) => {
  function noop(value) {
    return value;
  }
  function generateMultiplier(multiplier) {
    const { min, max, comma } = multiplier;
    if (min === 0 && max === 0) {
      return comma ? "#?" : "*";
    }
    if (min === 0 && max === 1) {
      return "?";
    }
    if (min === 1 && max === 0) {
      return comma ? "#" : "+";
    }
    if (min === 1 && max === 1) {
      return "";
    }
    return (comma ? "#" : "") + (min === max ? "{" + min + "}" : "{" + min + "," + (max !== 0 ? max : "") + "}");
  }
  function generateTypeOpts(node2) {
    switch (node2.type) {
      case "Range":
        return " [" + (node2.min === null ? "-∞" : node2.min) + "," + (node2.max === null ? "∞" : node2.max) + "]";
      default:
        throw new Error("Unknown node type `" + node2.type + "`");
    }
  }
  function generateSequence(node2, decorate, forceBraces, compact) {
    const combinator = node2.combinator === " " || compact ? node2.combinator : " " + node2.combinator + " ";
    const result = node2.terms.map((term) => internalGenerate(term, decorate, forceBraces, compact)).join(combinator);
    if (node2.explicit || forceBraces) {
      return (compact || result[0] === "," ? "[" : "[ ") + result + (compact ? "]" : " ]");
    }
    return result;
  }
  function internalGenerate(node2, decorate, forceBraces, compact) {
    let result;
    switch (node2.type) {
      case "Group":
        result = generateSequence(node2, decorate, forceBraces, compact) + (node2.disallowEmpty ? "!" : "");
        break;
      case "Multiplier":
        return internalGenerate(node2.term, decorate, forceBraces, compact) + decorate(generateMultiplier(node2), node2);
      case "Boolean":
        result = "<boolean-expr[" + internalGenerate(node2.term, decorate, forceBraces, compact) + "]>";
        break;
      case "Type":
        result = "<" + node2.name + (node2.opts ? decorate(generateTypeOpts(node2.opts), node2.opts) : "") + ">";
        break;
      case "Property":
        result = "<'" + node2.name + "'>";
        break;
      case "Keyword":
        result = node2.name;
        break;
      case "AtKeyword":
        result = "@" + node2.name;
        break;
      case "Function":
        result = node2.name + "(";
        break;
      case "String":
      case "Token":
        result = node2.value;
        break;
      case "Comma":
        result = ",";
        break;
      default:
        throw new Error("Unknown node type `" + node2.type + "`");
    }
    return decorate(result, node2);
  }
  function generate2(node2, options) {
    let decorate = noop;
    let forceBraces = false;
    let compact = false;
    if (typeof options === "function") {
      decorate = options;
    } else if (options) {
      forceBraces = Boolean(options.forceBraces);
      compact = Boolean(options.compact);
      if (typeof options.decorate === "function") {
        decorate = options.decorate;
      }
    }
    return internalGenerate(node2, decorate, forceBraces, compact);
  }
  exports.generate = generate2;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/error.cjs
var require_error = __commonJS((exports) => {
  var createCustomError = require_create_custom_error();
  var generate2 = require_generate();
  var defaultLoc = { offset: 0, line: 1, column: 1 };
  function locateMismatch(matchResult, node2) {
    const tokens = matchResult.tokens;
    const longestMatch = matchResult.longestMatch;
    const mismatchNode = longestMatch < tokens.length ? tokens[longestMatch].node || null : null;
    const badNode = mismatchNode !== node2 ? mismatchNode : null;
    let mismatchOffset = 0;
    let mismatchLength = 0;
    let entries = 0;
    let css = "";
    let start;
    let end;
    for (let i = 0;i < tokens.length; i++) {
      const token = tokens[i].value;
      if (i === longestMatch) {
        mismatchLength = token.length;
        mismatchOffset = css.length;
      }
      if (badNode !== null && tokens[i].node === badNode) {
        if (i <= longestMatch) {
          entries++;
        } else {
          entries = 0;
        }
      }
      css += token;
    }
    if (longestMatch === tokens.length || entries > 1) {
      start = fromLoc(badNode || node2, "end") || buildLoc(defaultLoc, css);
      end = buildLoc(start);
    } else {
      start = fromLoc(badNode, "start") || buildLoc(fromLoc(node2, "start") || defaultLoc, css.slice(0, mismatchOffset));
      end = fromLoc(badNode, "end") || buildLoc(start, css.substr(mismatchOffset, mismatchLength));
    }
    return {
      css,
      mismatchOffset,
      mismatchLength,
      start,
      end
    };
  }
  function fromLoc(node2, point) {
    const value = node2 && node2.loc && node2.loc[point];
    if (value) {
      return "line" in value ? buildLoc(value) : value;
    }
    return null;
  }
  function buildLoc({ offset, line, column }, extra) {
    const loc = {
      offset,
      line,
      column
    };
    if (extra) {
      const lines = extra.split(/\n|\r\n?|\f/);
      loc.offset += extra.length;
      loc.line += lines.length - 1;
      loc.column = lines.length === 1 ? loc.column + extra.length : lines.pop().length + 1;
    }
    return loc;
  }
  var SyntaxReferenceError = function(type, referenceName) {
    const error = createCustomError.createCustomError("SyntaxReferenceError", type + (referenceName ? " `" + referenceName + "`" : ""));
    error.reference = referenceName;
    return error;
  };
  var SyntaxMatchError = function(message, syntax, node2, matchResult) {
    const error = createCustomError.createCustomError("SyntaxMatchError", message);
    const {
      css,
      mismatchOffset,
      mismatchLength,
      start,
      end
    } = locateMismatch(matchResult, node2);
    error.rawMessage = message;
    error.syntax = syntax ? generate2.generate(syntax) : "<generic>";
    error.css = css;
    error.mismatchOffset = mismatchOffset;
    error.mismatchLength = mismatchLength;
    error.message = message + `
` + "  syntax: " + error.syntax + `
` + "   value: " + (css || "<empty string>") + `
` + "  --------" + new Array(error.mismatchOffset + 1).join("-") + "^";
    Object.assign(error, start);
    error.loc = {
      source: node2 && node2.loc && node2.loc.source || "<unknown>",
      start,
      end
    };
    return error;
  };
  exports.SyntaxMatchError = SyntaxMatchError;
  exports.SyntaxReferenceError = SyntaxReferenceError;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/names.cjs
var require_names2 = __commonJS((exports) => {
  var keywords = new Map;
  var properties = new Map;
  var HYPHENMINUS = 45;
  var keyword = getKeywordDescriptor;
  var property = getPropertyDescriptor;
  var vendorPrefix = getVendorPrefix;
  function isCustomProperty(str, offset) {
    offset = offset || 0;
    return str.length - offset >= 2 && str.charCodeAt(offset) === HYPHENMINUS && str.charCodeAt(offset + 1) === HYPHENMINUS;
  }
  function getVendorPrefix(str, offset) {
    offset = offset || 0;
    if (str.length - offset >= 3) {
      if (str.charCodeAt(offset) === HYPHENMINUS && str.charCodeAt(offset + 1) !== HYPHENMINUS) {
        const secondDashIndex = str.indexOf("-", offset + 2);
        if (secondDashIndex !== -1) {
          return str.substring(offset, secondDashIndex + 1);
        }
      }
    }
    return "";
  }
  function getKeywordDescriptor(keyword2) {
    if (keywords.has(keyword2)) {
      return keywords.get(keyword2);
    }
    const name = keyword2.toLowerCase();
    let descriptor = keywords.get(name);
    if (descriptor === undefined) {
      const custom = isCustomProperty(name, 0);
      const vendor = !custom ? getVendorPrefix(name, 0) : "";
      descriptor = Object.freeze({
        basename: name.substr(vendor.length),
        name,
        prefix: vendor,
        vendor,
        custom
      });
    }
    keywords.set(keyword2, descriptor);
    return descriptor;
  }
  function getPropertyDescriptor(property2) {
    if (properties.has(property2)) {
      return properties.get(property2);
    }
    let name = property2;
    let hack = property2[0];
    if (hack === "/") {
      hack = property2[1] === "/" ? "//" : "/";
    } else if (hack !== "_" && hack !== "*" && hack !== "$" && hack !== "#" && hack !== "+" && hack !== "&") {
      hack = "";
    }
    const custom = isCustomProperty(name, hack.length);
    if (!custom) {
      name = name.toLowerCase();
      if (properties.has(name)) {
        const descriptor2 = properties.get(name);
        properties.set(property2, descriptor2);
        return descriptor2;
      }
    }
    const vendor = !custom ? getVendorPrefix(name, hack.length) : "";
    const prefix = name.substr(0, hack.length + vendor.length);
    const descriptor = Object.freeze({
      basename: name.substr(prefix.length),
      name: name.substr(hack.length),
      hack,
      vendor,
      prefix,
      custom
    });
    properties.set(property2, descriptor);
    return descriptor;
  }
  exports.isCustomProperty = isCustomProperty;
  exports.keyword = keyword;
  exports.property = property;
  exports.vendorPrefix = vendorPrefix;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/generic-const.cjs
var require_generic_const = __commonJS((exports) => {
  var cssWideKeywords = [
    "initial",
    "inherit",
    "unset",
    "revert",
    "revert-layer"
  ];
  exports.cssWideKeywords = cssWideKeywords;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/generic-an-plus-b.cjs
var require_generic_an_plus_b = __commonJS((exports, module) => {
  var charCodeDefinitions = require_char_code_definitions();
  var types2 = require_types();
  var utils = require_utils();
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var N = 110;
  var DISALLOW_SIGN = true;
  var ALLOW_SIGN = false;
  function isDelim(token, code) {
    return token !== null && token.type === types2.Delim && token.value.charCodeAt(0) === code;
  }
  function skipSC(token, offset, getNextToken) {
    while (token !== null && (token.type === types2.WhiteSpace || token.type === types2.Comment)) {
      token = getNextToken(++offset);
    }
    return offset;
  }
  function checkInteger(token, valueOffset, disallowSign, offset) {
    if (!token) {
      return 0;
    }
    const code = token.value.charCodeAt(valueOffset);
    if (code === PLUSSIGN || code === HYPHENMINUS) {
      if (disallowSign) {
        return 0;
      }
      valueOffset++;
    }
    for (;valueOffset < token.value.length; valueOffset++) {
      if (!charCodeDefinitions.isDigit(token.value.charCodeAt(valueOffset))) {
        return 0;
      }
    }
    return offset + 1;
  }
  function consumeB(token, offset_, getNextToken) {
    let sign = false;
    let offset = skipSC(token, offset_, getNextToken);
    token = getNextToken(offset);
    if (token === null) {
      return offset_;
    }
    if (token.type !== types2.Number) {
      if (isDelim(token, PLUSSIGN) || isDelim(token, HYPHENMINUS)) {
        sign = true;
        offset = skipSC(getNextToken(++offset), offset, getNextToken);
        token = getNextToken(offset);
        if (token === null || token.type !== types2.Number) {
          return 0;
        }
      } else {
        return offset_;
      }
    }
    if (!sign) {
      const code = token.value.charCodeAt(0);
      if (code !== PLUSSIGN && code !== HYPHENMINUS) {
        return 0;
      }
    }
    return checkInteger(token, sign ? 0 : 1, sign, offset);
  }
  function anPlusB(token, getNextToken) {
    let offset = 0;
    if (!token) {
      return 0;
    }
    if (token.type === types2.Number) {
      return checkInteger(token, 0, ALLOW_SIGN, offset);
    } else if (token.type === types2.Ident && token.value.charCodeAt(0) === HYPHENMINUS) {
      if (!utils.cmpChar(token.value, 1, N)) {
        return 0;
      }
      switch (token.value.length) {
        case 2:
          return consumeB(getNextToken(++offset), offset, getNextToken);
        case 3:
          if (token.value.charCodeAt(2) !== HYPHENMINUS) {
            return 0;
          }
          offset = skipSC(getNextToken(++offset), offset, getNextToken);
          token = getNextToken(offset);
          return checkInteger(token, 0, DISALLOW_SIGN, offset);
        default:
          if (token.value.charCodeAt(2) !== HYPHENMINUS) {
            return 0;
          }
          return checkInteger(token, 3, DISALLOW_SIGN, offset);
      }
    } else if (token.type === types2.Ident || isDelim(token, PLUSSIGN) && getNextToken(offset + 1).type === types2.Ident) {
      if (token.type !== types2.Ident) {
        token = getNextToken(++offset);
      }
      if (token === null || !utils.cmpChar(token.value, 0, N)) {
        return 0;
      }
      switch (token.value.length) {
        case 1:
          return consumeB(getNextToken(++offset), offset, getNextToken);
        case 2:
          if (token.value.charCodeAt(1) !== HYPHENMINUS) {
            return 0;
          }
          offset = skipSC(getNextToken(++offset), offset, getNextToken);
          token = getNextToken(offset);
          return checkInteger(token, 0, DISALLOW_SIGN, offset);
        default:
          if (token.value.charCodeAt(1) !== HYPHENMINUS) {
            return 0;
          }
          return checkInteger(token, 2, DISALLOW_SIGN, offset);
      }
    } else if (token.type === types2.Dimension) {
      let code = token.value.charCodeAt(0);
      let sign = code === PLUSSIGN || code === HYPHENMINUS ? 1 : 0;
      let i = sign;
      for (;i < token.value.length; i++) {
        if (!charCodeDefinitions.isDigit(token.value.charCodeAt(i))) {
          break;
        }
      }
      if (i === sign) {
        return 0;
      }
      if (!utils.cmpChar(token.value, i, N)) {
        return 0;
      }
      if (i + 1 === token.value.length) {
        return consumeB(getNextToken(++offset), offset, getNextToken);
      } else {
        if (token.value.charCodeAt(i + 1) !== HYPHENMINUS) {
          return 0;
        }
        if (i + 2 === token.value.length) {
          offset = skipSC(getNextToken(++offset), offset, getNextToken);
          token = getNextToken(offset);
          return checkInteger(token, 0, DISALLOW_SIGN, offset);
        } else {
          return checkInteger(token, i + 2, DISALLOW_SIGN, offset);
        }
      }
    }
    return 0;
  }
  module.exports = anPlusB;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/generic-urange.cjs
var require_generic_urange = __commonJS((exports, module) => {
  var charCodeDefinitions = require_char_code_definitions();
  var types2 = require_types();
  var utils = require_utils();
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var QUESTIONMARK = 63;
  var U = 117;
  function isDelim(token, code) {
    return token !== null && token.type === types2.Delim && token.value.charCodeAt(0) === code;
  }
  function startsWith(token, code) {
    return token.value.charCodeAt(0) === code;
  }
  function hexSequence(token, offset, allowDash) {
    let hexlen = 0;
    for (let pos = offset;pos < token.value.length; pos++) {
      const code = token.value.charCodeAt(pos);
      if (code === HYPHENMINUS && allowDash && hexlen !== 0) {
        hexSequence(token, offset + hexlen + 1, false);
        return 6;
      }
      if (!charCodeDefinitions.isHexDigit(code)) {
        return 0;
      }
      if (++hexlen > 6) {
        return 0;
      }
    }
    return hexlen;
  }
  function withQuestionMarkSequence(consumed, length, getNextToken) {
    if (!consumed) {
      return 0;
    }
    while (isDelim(getNextToken(length), QUESTIONMARK)) {
      if (++consumed > 6) {
        return 0;
      }
      length++;
    }
    return length;
  }
  function urange(token, getNextToken) {
    let length = 0;
    if (token === null || token.type !== types2.Ident || !utils.cmpChar(token.value, 0, U)) {
      return 0;
    }
    token = getNextToken(++length);
    if (token === null) {
      return 0;
    }
    if (isDelim(token, PLUSSIGN)) {
      token = getNextToken(++length);
      if (token === null) {
        return 0;
      }
      if (token.type === types2.Ident) {
        return withQuestionMarkSequence(hexSequence(token, 0, true), ++length, getNextToken);
      }
      if (isDelim(token, QUESTIONMARK)) {
        return withQuestionMarkSequence(1, ++length, getNextToken);
      }
      return 0;
    }
    if (token.type === types2.Number) {
      const consumedHexLength = hexSequence(token, 1, true);
      if (consumedHexLength === 0) {
        return 0;
      }
      token = getNextToken(++length);
      if (token === null) {
        return length;
      }
      if (token.type === types2.Dimension || token.type === types2.Number) {
        if (!startsWith(token, HYPHENMINUS) || !hexSequence(token, 1, false)) {
          return 0;
        }
        return length + 1;
      }
      return withQuestionMarkSequence(consumedHexLength, length, getNextToken);
    }
    if (token.type === types2.Dimension) {
      return withQuestionMarkSequence(hexSequence(token, 1, true), ++length, getNextToken);
    }
    return 0;
  }
  module.exports = urange;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/generic.cjs
var require_generic = __commonJS((exports) => {
  var genericConst = require_generic_const();
  var genericAnPlusB = require_generic_an_plus_b();
  var genericUrange = require_generic_urange();
  var charCodeDefinitions = require_char_code_definitions();
  var types2 = require_types();
  var utils = require_utils();
  var calcFunctionNames = [
    "calc(",
    "-moz-calc(",
    "-webkit-calc("
  ];
  var comparisonFunctionNames = [
    "min(",
    "max(",
    "clamp("
  ];
  var steppedValueFunctionNames = [
    "round(",
    "mod(",
    "rem("
  ];
  var trigNumberFunctionNames = [
    "sin(",
    "cos(",
    "tan("
  ];
  var trigAngleFunctionNames = [
    "asin(",
    "acos(",
    "atan(",
    "atan2("
  ];
  var otherNumberFunctionNames = [
    "pow(",
    "sqrt(",
    "log(",
    "exp(",
    "sign("
  ];
  var expNumberDimensionPercentageFunctionNames = [
    "hypot("
  ];
  var signFunctionNames = [
    "abs("
  ];
  var numberFunctionNames = [
    ...calcFunctionNames,
    ...comparisonFunctionNames,
    ...steppedValueFunctionNames,
    ...trigNumberFunctionNames,
    ...otherNumberFunctionNames,
    ...expNumberDimensionPercentageFunctionNames,
    ...signFunctionNames
  ];
  var percentageFunctionNames = [
    ...calcFunctionNames,
    ...comparisonFunctionNames,
    ...steppedValueFunctionNames,
    ...expNumberDimensionPercentageFunctionNames,
    ...signFunctionNames
  ];
  var dimensionFunctionNames = [
    ...calcFunctionNames,
    ...comparisonFunctionNames,
    ...steppedValueFunctionNames,
    ...trigAngleFunctionNames,
    ...expNumberDimensionPercentageFunctionNames,
    ...signFunctionNames
  ];
  var balancePair = new Map([
    [types2.Function, types2.RightParenthesis],
    [types2.LeftParenthesis, types2.RightParenthesis],
    [types2.LeftSquareBracket, types2.RightSquareBracket],
    [types2.LeftCurlyBracket, types2.RightCurlyBracket]
  ]);
  function charCodeAt(str, index) {
    return index < str.length ? str.charCodeAt(index) : 0;
  }
  function eqStr(actual, expected) {
    return utils.cmpStr(actual, 0, actual.length, expected);
  }
  function eqStrAny(actual, expected) {
    for (let i = 0;i < expected.length; i++) {
      if (eqStr(actual, expected[i])) {
        return true;
      }
    }
    return false;
  }
  function isPostfixIeHack(str, offset) {
    if (offset !== str.length - 2) {
      return false;
    }
    return charCodeAt(str, offset) === 92 && charCodeDefinitions.isDigit(charCodeAt(str, offset + 1));
  }
  function outOfRange(opts, value, numEnd) {
    if (opts && opts.type === "Range") {
      const num = Number(numEnd !== undefined && numEnd !== value.length ? value.substr(0, numEnd) : value);
      if (isNaN(num)) {
        return true;
      }
      if (opts.min !== null && num < opts.min && typeof opts.min !== "string") {
        return true;
      }
      if (opts.max !== null && num > opts.max && typeof opts.max !== "string") {
        return true;
      }
    }
    return false;
  }
  function consumeFunction(token, getNextToken) {
    let balanceCloseType = 0;
    let balanceStash = [];
    let length = 0;
    scan:
      do {
        switch (token.type) {
          case types2.RightCurlyBracket:
          case types2.RightParenthesis:
          case types2.RightSquareBracket:
            if (token.type !== balanceCloseType) {
              break scan;
            }
            balanceCloseType = balanceStash.pop();
            if (balanceStash.length === 0) {
              length++;
              break scan;
            }
            break;
          case types2.Function:
          case types2.LeftParenthesis:
          case types2.LeftSquareBracket:
          case types2.LeftCurlyBracket:
            balanceStash.push(balanceCloseType);
            balanceCloseType = balancePair.get(token.type);
            break;
        }
        length++;
      } while (token = getNextToken(length));
    return length;
  }
  function math(next, functionNames) {
    return function(token, getNextToken, opts) {
      if (token === null) {
        return 0;
      }
      if (token.type === types2.Function && eqStrAny(token.value, functionNames)) {
        return consumeFunction(token, getNextToken);
      }
      return next(token, getNextToken, opts);
    };
  }
  function tokenType(expectedTokenType) {
    return function(token) {
      if (token === null || token.type !== expectedTokenType) {
        return 0;
      }
      return 1;
    };
  }
  function customIdent(token) {
    if (token === null || token.type !== types2.Ident) {
      return 0;
    }
    const name = token.value.toLowerCase();
    if (eqStrAny(name, genericConst.cssWideKeywords)) {
      return 0;
    }
    if (eqStr(name, "default")) {
      return 0;
    }
    return 1;
  }
  function dashedIdent(token) {
    if (token === null || token.type !== types2.Ident) {
      return 0;
    }
    if (charCodeAt(token.value, 0) !== 45 || charCodeAt(token.value, 1) !== 45) {
      return 0;
    }
    return 1;
  }
  function customPropertyName(token) {
    if (!dashedIdent(token)) {
      return 0;
    }
    if (token.value === "--") {
      return 0;
    }
    return 1;
  }
  function hexColor(token) {
    if (token === null || token.type !== types2.Hash) {
      return 0;
    }
    const length = token.value.length;
    if (length !== 4 && length !== 5 && length !== 7 && length !== 9) {
      return 0;
    }
    for (let i = 1;i < length; i++) {
      if (!charCodeDefinitions.isHexDigit(charCodeAt(token.value, i))) {
        return 0;
      }
    }
    return 1;
  }
  function idSelector(token) {
    if (token === null || token.type !== types2.Hash) {
      return 0;
    }
    if (!charCodeDefinitions.isIdentifierStart(charCodeAt(token.value, 1), charCodeAt(token.value, 2), charCodeAt(token.value, 3))) {
      return 0;
    }
    return 1;
  }
  function declarationValue(token, getNextToken) {
    if (!token) {
      return 0;
    }
    let balanceCloseType = 0;
    let balanceStash = [];
    let length = 0;
    scan:
      do {
        switch (token.type) {
          case types2.BadString:
          case types2.BadUrl:
            break scan;
          case types2.RightCurlyBracket:
          case types2.RightParenthesis:
          case types2.RightSquareBracket:
            if (token.type !== balanceCloseType) {
              break scan;
            }
            balanceCloseType = balanceStash.pop();
            break;
          case types2.Semicolon:
            if (balanceCloseType === 0) {
              break scan;
            }
            break;
          case types2.Delim:
            if (balanceCloseType === 0 && token.value === "!") {
              break scan;
            }
            break;
          case types2.Function:
          case types2.LeftParenthesis:
          case types2.LeftSquareBracket:
          case types2.LeftCurlyBracket:
            balanceStash.push(balanceCloseType);
            balanceCloseType = balancePair.get(token.type);
            break;
        }
        length++;
      } while (token = getNextToken(length));
    return length;
  }
  function anyValue(token, getNextToken) {
    if (!token) {
      return 0;
    }
    let balanceCloseType = 0;
    let balanceStash = [];
    let length = 0;
    scan:
      do {
        switch (token.type) {
          case types2.BadString:
          case types2.BadUrl:
            break scan;
          case types2.RightCurlyBracket:
          case types2.RightParenthesis:
          case types2.RightSquareBracket:
            if (token.type !== balanceCloseType) {
              break scan;
            }
            balanceCloseType = balanceStash.pop();
            break;
          case types2.Function:
          case types2.LeftParenthesis:
          case types2.LeftSquareBracket:
          case types2.LeftCurlyBracket:
            balanceStash.push(balanceCloseType);
            balanceCloseType = balancePair.get(token.type);
            break;
        }
        length++;
      } while (token = getNextToken(length));
    return length;
  }
  function dimension(type) {
    if (type) {
      type = new Set(type);
    }
    return function(token, getNextToken, opts) {
      if (token === null || token.type !== types2.Dimension) {
        return 0;
      }
      const numberEnd = utils.consumeNumber(token.value, 0);
      if (type !== null) {
        const reverseSolidusOffset = token.value.indexOf("\\", numberEnd);
        const unit = reverseSolidusOffset === -1 || !isPostfixIeHack(token.value, reverseSolidusOffset) ? token.value.substr(numberEnd) : token.value.substring(numberEnd, reverseSolidusOffset);
        if (type.has(unit.toLowerCase()) === false) {
          return 0;
        }
      }
      if (outOfRange(opts, token.value, numberEnd)) {
        return 0;
      }
      return 1;
    };
  }
  function percentage(token, getNextToken, opts) {
    if (token === null || token.type !== types2.Percentage) {
      return 0;
    }
    if (outOfRange(opts, token.value, token.value.length - 1)) {
      return 0;
    }
    return 1;
  }
  function zero(next) {
    if (typeof next !== "function") {
      next = function() {
        return 0;
      };
    }
    return function(token, getNextToken, opts) {
      if (token !== null && token.type === types2.Number) {
        if (Number(token.value) === 0) {
          return 1;
        }
      }
      return next(token, getNextToken, opts);
    };
  }
  function number(token, getNextToken, opts) {
    if (token === null) {
      return 0;
    }
    const numberEnd = utils.consumeNumber(token.value, 0);
    const isNumber2 = numberEnd === token.value.length;
    if (!isNumber2 && !isPostfixIeHack(token.value, numberEnd)) {
      return 0;
    }
    if (outOfRange(opts, token.value, numberEnd)) {
      return 0;
    }
    return 1;
  }
  function integer(token, getNextToken, opts) {
    if (token === null || token.type !== types2.Number) {
      return 0;
    }
    let i = charCodeAt(token.value, 0) === 43 || charCodeAt(token.value, 0) === 45 ? 1 : 0;
    for (;i < token.value.length; i++) {
      if (!charCodeDefinitions.isDigit(charCodeAt(token.value, i))) {
        return 0;
      }
    }
    if (outOfRange(opts, token.value, i)) {
      return 0;
    }
    return 1;
  }
  var tokenTypes = {
    "ident-token": tokenType(types2.Ident),
    "function-token": tokenType(types2.Function),
    "at-keyword-token": tokenType(types2.AtKeyword),
    "hash-token": tokenType(types2.Hash),
    "string-token": tokenType(types2.String),
    "bad-string-token": tokenType(types2.BadString),
    "url-token": tokenType(types2.Url),
    "bad-url-token": tokenType(types2.BadUrl),
    "delim-token": tokenType(types2.Delim),
    "number-token": tokenType(types2.Number),
    "percentage-token": tokenType(types2.Percentage),
    "dimension-token": tokenType(types2.Dimension),
    "whitespace-token": tokenType(types2.WhiteSpace),
    "CDO-token": tokenType(types2.CDO),
    "CDC-token": tokenType(types2.CDC),
    "colon-token": tokenType(types2.Colon),
    "semicolon-token": tokenType(types2.Semicolon),
    "comma-token": tokenType(types2.Comma),
    "[-token": tokenType(types2.LeftSquareBracket),
    "]-token": tokenType(types2.RightSquareBracket),
    "(-token": tokenType(types2.LeftParenthesis),
    ")-token": tokenType(types2.RightParenthesis),
    "{-token": tokenType(types2.LeftCurlyBracket),
    "}-token": tokenType(types2.RightCurlyBracket)
  };
  var productionTypes = {
    string: tokenType(types2.String),
    ident: tokenType(types2.Ident),
    percentage: math(percentage, percentageFunctionNames),
    zero: zero(),
    number: math(number, numberFunctionNames),
    integer: math(integer, numberFunctionNames),
    "custom-ident": customIdent,
    "dashed-ident": dashedIdent,
    "custom-property-name": customPropertyName,
    "hex-color": hexColor,
    "id-selector": idSelector,
    "an-plus-b": genericAnPlusB,
    urange: genericUrange,
    "declaration-value": declarationValue,
    "any-value": anyValue
  };
  var unitGroups = [
    "length",
    "angle",
    "time",
    "frequency",
    "resolution",
    "flex",
    "decibel",
    "semitones"
  ];
  function createDemensionTypes(units) {
    const {
      angle,
      decibel,
      frequency,
      flex,
      length,
      resolution,
      semitones,
      time
    } = units || {};
    return {
      dimension: math(dimension(null), dimensionFunctionNames),
      angle: math(dimension(angle), dimensionFunctionNames),
      decibel: math(dimension(decibel), dimensionFunctionNames),
      frequency: math(dimension(frequency), dimensionFunctionNames),
      flex: math(dimension(flex), dimensionFunctionNames),
      length: math(zero(dimension(length)), dimensionFunctionNames),
      resolution: math(dimension(resolution), dimensionFunctionNames),
      semitones: math(dimension(semitones), dimensionFunctionNames),
      time: math(dimension(time), dimensionFunctionNames)
    };
  }
  function createAttrUnit(units) {
    const unitSet = new Set;
    for (const group of unitGroups) {
      if (Array.isArray(units[group])) {
        for (const unit of units[group]) {
          unitSet.add(unit.toLowerCase());
        }
      }
    }
    return function attrUnit(token) {
      if (token === null) {
        return 0;
      }
      if (token.type === types2.Delim && token.value === "%") {
        return 1;
      }
      if (token.type === types2.Ident && unitSet.has(token.value.toLowerCase())) {
        return 1;
      }
      return 0;
    };
  }
  function createGenericTypes(units) {
    return {
      ...tokenTypes,
      ...productionTypes,
      ...createDemensionTypes(units),
      "attr-unit": createAttrUnit(units)
    };
  }
  exports.createDemensionTypes = createDemensionTypes;
  exports.createGenericTypes = createGenericTypes;
  exports.productionTypes = productionTypes;
  exports.tokenTypes = tokenTypes;
  exports.unitGroups = unitGroups;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/units.cjs
var require_units = __commonJS((exports) => {
  var length = [
    "cm",
    "mm",
    "q",
    "in",
    "pt",
    "pc",
    "px",
    "em",
    "rem",
    "ex",
    "rex",
    "cap",
    "rcap",
    "ch",
    "rch",
    "ic",
    "ric",
    "lh",
    "rlh",
    "vw",
    "svw",
    "lvw",
    "dvw",
    "vh",
    "svh",
    "lvh",
    "dvh",
    "vi",
    "svi",
    "lvi",
    "dvi",
    "vb",
    "svb",
    "lvb",
    "dvb",
    "vmin",
    "svmin",
    "lvmin",
    "dvmin",
    "vmax",
    "svmax",
    "lvmax",
    "dvmax",
    "cqw",
    "cqh",
    "cqi",
    "cqb",
    "cqmin",
    "cqmax"
  ];
  var angle = ["deg", "grad", "rad", "turn"];
  var time = ["s", "ms"];
  var frequency = ["hz", "khz"];
  var resolution = ["dpi", "dpcm", "dppx", "x"];
  var flex = ["fr"];
  var decibel = ["db"];
  var semitones = ["st"];
  exports.angle = angle;
  exports.decibel = decibel;
  exports.flex = flex;
  exports.frequency = frequency;
  exports.length = length;
  exports.resolution = resolution;
  exports.semitones = semitones;
  exports.time = time;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/prepare-tokens.cjs
var require_prepare_tokens = __commonJS((exports, module) => {
  var index = require_tokenizer();
  var astToTokens = {
    decorator(handlers) {
      const tokens = [];
      let curNode = null;
      return {
        ...handlers,
        node(node2) {
          const tmp = curNode;
          curNode = node2;
          handlers.node.call(this, node2);
          curNode = tmp;
        },
        emit(value, type, auto) {
          tokens.push({
            type,
            value,
            node: auto ? null : curNode
          });
        },
        result() {
          return tokens;
        }
      };
    }
  };
  function stringToTokens(str) {
    const tokens = [];
    index.tokenize(str, (type, start, end) => tokens.push({
      type,
      value: str.slice(start, end),
      node: null
    }));
    return tokens;
  }
  function prepareTokens(value, syntax) {
    if (typeof value === "string") {
      return stringToTokens(value);
    }
    return syntax.generate(value, astToTokens);
  }
  module.exports = prepareTokens;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/SyntaxError.cjs
var require_SyntaxError2 = __commonJS((exports) => {
  var createCustomError = require_create_custom_error();
  function SyntaxError2(message, input, offset) {
    return Object.assign(createCustomError.createCustomError("SyntaxError", message), {
      input,
      offset,
      rawMessage: message,
      message: message + `
` + "  " + input + `
` + "--" + new Array((offset || input.length) + 1).join("-") + "^"
    });
  }
  exports.SyntaxError = SyntaxError2;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/scanner.cjs
var require_scanner = __commonJS((exports) => {
  var SyntaxError2 = require_SyntaxError2();
  var TAB = 9;
  var N = 10;
  var F = 12;
  var R = 13;
  var SPACE = 32;
  var NAME_CHAR = new Uint8Array(128).map((_, idx) => /[a-zA-Z0-9\-]/.test(String.fromCharCode(idx)) ? 1 : 0);

  class Scanner {
    constructor(str) {
      this.str = str;
      this.pos = 0;
    }
    charCodeAt(pos) {
      return pos < this.str.length ? this.str.charCodeAt(pos) : 0;
    }
    charCode() {
      return this.charCodeAt(this.pos);
    }
    isNameCharCode(code = this.charCode()) {
      return code < 128 && NAME_CHAR[code] === 1;
    }
    nextCharCode() {
      return this.charCodeAt(this.pos + 1);
    }
    nextNonWsCode(pos) {
      return this.charCodeAt(this.findWsEnd(pos));
    }
    skipWs() {
      this.pos = this.findWsEnd(this.pos);
    }
    findWsEnd(pos) {
      for (;pos < this.str.length; pos++) {
        const code = this.str.charCodeAt(pos);
        if (code !== R && code !== N && code !== F && code !== SPACE && code !== TAB) {
          break;
        }
      }
      return pos;
    }
    substringToPos(end) {
      return this.str.substring(this.pos, this.pos = end);
    }
    eat(code) {
      if (this.charCode() !== code) {
        this.error("Expect `" + String.fromCharCode(code) + "`");
      }
      this.pos++;
    }
    peek() {
      return this.pos < this.str.length ? this.str.charAt(this.pos++) : "";
    }
    error(message) {
      throw new SyntaxError2.SyntaxError(message, this.str, this.pos);
    }
    scanSpaces() {
      return this.substringToPos(this.findWsEnd(this.pos));
    }
    scanWord() {
      let end = this.pos;
      for (;end < this.str.length; end++) {
        const code = this.str.charCodeAt(end);
        if (code >= 128 || NAME_CHAR[code] === 0) {
          break;
        }
      }
      if (this.pos === end) {
        this.error("Expect a keyword");
      }
      return this.substringToPos(end);
    }
    scanNumber() {
      let end = this.pos;
      for (;end < this.str.length; end++) {
        const code = this.str.charCodeAt(end);
        if (code < 48 || code > 57) {
          break;
        }
      }
      if (this.pos === end) {
        this.error("Expect a number");
      }
      return this.substringToPos(end);
    }
    scanString() {
      const end = this.str.indexOf("'", this.pos + 1);
      if (end === -1) {
        this.pos = this.str.length;
        this.error("Expect an apostrophe");
      }
      return this.substringToPos(end + 1);
    }
  }
  exports.Scanner = Scanner;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/parse.cjs
var require_parse = __commonJS((exports) => {
  var scanner = require_scanner();
  var TAB = 9;
  var N = 10;
  var F = 12;
  var R = 13;
  var SPACE = 32;
  var EXCLAMATIONMARK = 33;
  var NUMBERSIGN = 35;
  var AMPERSAND = 38;
  var APOSTROPHE = 39;
  var LEFTPARENTHESIS = 40;
  var RIGHTPARENTHESIS = 41;
  var ASTERISK = 42;
  var PLUSSIGN = 43;
  var COMMA = 44;
  var HYPERMINUS = 45;
  var LESSTHANSIGN = 60;
  var GREATERTHANSIGN = 62;
  var QUESTIONMARK = 63;
  var COMMERCIALAT = 64;
  var LEFTSQUAREBRACKET = 91;
  var RIGHTSQUAREBRACKET = 93;
  var LEFTCURLYBRACKET = 123;
  var VERTICALLINE = 124;
  var RIGHTCURLYBRACKET = 125;
  var INFINITY = 8734;
  var COMBINATOR_PRECEDENCE = {
    " ": 1,
    "&&": 2,
    "||": 3,
    "|": 4
  };
  function readMultiplierRange(scanner2) {
    let min = null;
    let max = null;
    scanner2.eat(LEFTCURLYBRACKET);
    scanner2.skipWs();
    min = scanner2.scanNumber(scanner2);
    scanner2.skipWs();
    if (scanner2.charCode() === COMMA) {
      scanner2.pos++;
      scanner2.skipWs();
      if (scanner2.charCode() !== RIGHTCURLYBRACKET) {
        max = scanner2.scanNumber(scanner2);
        scanner2.skipWs();
      }
    } else {
      max = min;
    }
    scanner2.eat(RIGHTCURLYBRACKET);
    return {
      min: Number(min),
      max: max ? Number(max) : 0
    };
  }
  function readMultiplier(scanner2) {
    let range = null;
    let comma = false;
    switch (scanner2.charCode()) {
      case ASTERISK:
        scanner2.pos++;
        range = {
          min: 0,
          max: 0
        };
        break;
      case PLUSSIGN:
        scanner2.pos++;
        range = {
          min: 1,
          max: 0
        };
        break;
      case QUESTIONMARK:
        scanner2.pos++;
        range = {
          min: 0,
          max: 1
        };
        break;
      case NUMBERSIGN:
        scanner2.pos++;
        comma = true;
        if (scanner2.charCode() === LEFTCURLYBRACKET) {
          range = readMultiplierRange(scanner2);
        } else if (scanner2.charCode() === QUESTIONMARK) {
          scanner2.pos++;
          range = {
            min: 0,
            max: 0
          };
        } else {
          range = {
            min: 1,
            max: 0
          };
        }
        break;
      case LEFTCURLYBRACKET:
        range = readMultiplierRange(scanner2);
        break;
      default:
        return null;
    }
    return {
      type: "Multiplier",
      comma,
      min: range.min,
      max: range.max,
      term: null
    };
  }
  function maybeMultiplied(scanner2, node2) {
    const multiplier = readMultiplier(scanner2);
    if (multiplier !== null) {
      multiplier.term = node2;
      if (scanner2.charCode() === NUMBERSIGN && scanner2.charCodeAt(scanner2.pos - 1) === PLUSSIGN) {
        return maybeMultiplied(scanner2, multiplier);
      }
      if (scanner2.charCode() === QUESTIONMARK && scanner2.charCodeAt(scanner2.pos - 1) === RIGHTCURLYBRACKET) {
        return maybeMultiplied(scanner2, multiplier);
      }
      return multiplier;
    }
    return node2;
  }
  function maybeToken(scanner2) {
    const ch = scanner2.peek();
    if (ch === "") {
      return null;
    }
    return maybeMultiplied(scanner2, {
      type: "Token",
      value: ch
    });
  }
  function readProperty(scanner2) {
    let name;
    scanner2.eat(LESSTHANSIGN);
    scanner2.eat(APOSTROPHE);
    name = scanner2.scanWord();
    scanner2.eat(APOSTROPHE);
    scanner2.eat(GREATERTHANSIGN);
    return maybeMultiplied(scanner2, {
      type: "Property",
      name
    });
  }
  function readTypeRange(scanner2) {
    let min = null;
    let max = null;
    let sign = 1;
    scanner2.eat(LEFTSQUAREBRACKET);
    if (scanner2.charCode() === HYPERMINUS) {
      scanner2.peek();
      sign = -1;
    }
    if (sign == -1 && scanner2.charCode() === INFINITY) {
      scanner2.peek();
    } else {
      min = sign * Number(scanner2.scanNumber(scanner2));
      if (scanner2.isNameCharCode()) {
        min += scanner2.scanWord();
      }
    }
    scanner2.skipWs();
    scanner2.eat(COMMA);
    scanner2.skipWs();
    if (scanner2.charCode() === INFINITY) {
      scanner2.peek();
    } else {
      sign = 1;
      if (scanner2.charCode() === HYPERMINUS) {
        scanner2.peek();
        sign = -1;
      }
      max = sign * Number(scanner2.scanNumber(scanner2));
      if (scanner2.isNameCharCode()) {
        max += scanner2.scanWord();
      }
    }
    scanner2.eat(RIGHTSQUAREBRACKET);
    return {
      type: "Range",
      min,
      max
    };
  }
  function readType(scanner2) {
    let name;
    let opts = null;
    scanner2.eat(LESSTHANSIGN);
    name = scanner2.scanWord();
    if (name === "boolean-expr") {
      scanner2.eat(LEFTSQUAREBRACKET);
      const implicitGroup = readImplicitGroup(scanner2, RIGHTSQUAREBRACKET);
      scanner2.eat(RIGHTSQUAREBRACKET);
      scanner2.eat(GREATERTHANSIGN);
      return maybeMultiplied(scanner2, {
        type: "Boolean",
        term: implicitGroup.terms.length === 1 ? implicitGroup.terms[0] : implicitGroup
      });
    }
    if (scanner2.charCode() === LEFTPARENTHESIS && scanner2.nextCharCode() === RIGHTPARENTHESIS) {
      scanner2.pos += 2;
      name += "()";
    }
    if (scanner2.charCodeAt(scanner2.findWsEnd(scanner2.pos)) === LEFTSQUAREBRACKET) {
      scanner2.skipWs();
      opts = readTypeRange(scanner2);
    }
    scanner2.eat(GREATERTHANSIGN);
    return maybeMultiplied(scanner2, {
      type: "Type",
      name,
      opts
    });
  }
  function readKeywordOrFunction(scanner2) {
    const name = scanner2.scanWord();
    if (scanner2.charCode() === LEFTPARENTHESIS) {
      scanner2.pos++;
      return {
        type: "Function",
        name
      };
    }
    return maybeMultiplied(scanner2, {
      type: "Keyword",
      name
    });
  }
  function regroupTerms(terms, combinators) {
    function createGroup(terms2, combinator2) {
      return {
        type: "Group",
        terms: terms2,
        combinator: combinator2,
        disallowEmpty: false,
        explicit: false
      };
    }
    let combinator;
    combinators = Object.keys(combinators).sort((a, b) => COMBINATOR_PRECEDENCE[a] - COMBINATOR_PRECEDENCE[b]);
    while (combinators.length > 0) {
      combinator = combinators.shift();
      let i = 0;
      let subgroupStart = 0;
      for (;i < terms.length; i++) {
        const term = terms[i];
        if (term.type === "Combinator") {
          if (term.value === combinator) {
            if (subgroupStart === -1) {
              subgroupStart = i - 1;
            }
            terms.splice(i, 1);
            i--;
          } else {
            if (subgroupStart !== -1 && i - subgroupStart > 1) {
              terms.splice(subgroupStart, i - subgroupStart, createGroup(terms.slice(subgroupStart, i), combinator));
              i = subgroupStart + 1;
            }
            subgroupStart = -1;
          }
        }
      }
      if (subgroupStart !== -1 && combinators.length) {
        terms.splice(subgroupStart, i - subgroupStart, createGroup(terms.slice(subgroupStart, i), combinator));
      }
    }
    return combinator;
  }
  function readImplicitGroup(scanner2, stopCharCode = -1) {
    const combinators = Object.create(null);
    const terms = [];
    let prevToken = null;
    let prevTokenPos = scanner2.pos;
    let prevTokenIsFunction = false;
    while (scanner2.charCode() !== stopCharCode) {
      let token = prevTokenIsFunction ? readImplicitGroup(scanner2, RIGHTPARENTHESIS) : peek(scanner2);
      if (!token) {
        break;
      }
      if (token.type === "Spaces") {
        continue;
      }
      if (prevTokenIsFunction) {
        if (token.terms.length === 0) {
          prevTokenIsFunction = false;
          continue;
        }
        if (token.combinator === " ") {
          while (token.terms.length > 1) {
            combinators[" "] = true;
            terms.push({
              type: "Combinator",
              value: " "
            }, token.terms.shift());
          }
          token = token.terms[0];
        }
      }
      if (token.type === "Combinator") {
        if (prevToken === null || prevToken.type === "Combinator") {
          scanner2.pos = prevTokenPos;
          scanner2.error("Unexpected combinator");
        }
        combinators[token.value] = true;
      } else if (prevToken !== null && prevToken.type !== "Combinator") {
        combinators[" "] = true;
        terms.push({
          type: "Combinator",
          value: " "
        });
      }
      terms.push(token);
      prevToken = token;
      prevTokenPos = scanner2.pos;
      prevTokenIsFunction = token.type === "Function";
    }
    if (prevToken !== null && prevToken.type === "Combinator") {
      scanner2.pos -= prevTokenPos;
      scanner2.error("Unexpected combinator");
    }
    return {
      type: "Group",
      terms,
      combinator: regroupTerms(terms, combinators) || " ",
      disallowEmpty: false,
      explicit: false
    };
  }
  function readGroup(scanner2) {
    let result;
    scanner2.eat(LEFTSQUAREBRACKET);
    result = readImplicitGroup(scanner2, RIGHTSQUAREBRACKET);
    scanner2.eat(RIGHTSQUAREBRACKET);
    result.explicit = true;
    if (scanner2.charCode() === EXCLAMATIONMARK) {
      scanner2.pos++;
      result.disallowEmpty = true;
    }
    return result;
  }
  function peek(scanner2) {
    let code = scanner2.charCode();
    switch (code) {
      case RIGHTSQUAREBRACKET:
        break;
      case LEFTSQUAREBRACKET:
        return maybeMultiplied(scanner2, readGroup(scanner2));
      case LESSTHANSIGN:
        return scanner2.nextCharCode() === APOSTROPHE ? readProperty(scanner2) : readType(scanner2);
      case VERTICALLINE:
        return {
          type: "Combinator",
          value: scanner2.substringToPos(scanner2.pos + (scanner2.nextCharCode() === VERTICALLINE ? 2 : 1))
        };
      case AMPERSAND:
        scanner2.pos++;
        scanner2.eat(AMPERSAND);
        return {
          type: "Combinator",
          value: "&&"
        };
      case COMMA:
        scanner2.pos++;
        return {
          type: "Comma"
        };
      case APOSTROPHE:
        return maybeMultiplied(scanner2, {
          type: "String",
          value: scanner2.scanString()
        });
      case SPACE:
      case TAB:
      case N:
      case R:
      case F:
        return {
          type: "Spaces",
          value: scanner2.scanSpaces()
        };
      case COMMERCIALAT:
        code = scanner2.nextCharCode();
        if (scanner2.isNameCharCode(code)) {
          scanner2.pos++;
          return {
            type: "AtKeyword",
            name: scanner2.scanWord()
          };
        }
        return maybeToken(scanner2);
      case ASTERISK:
      case PLUSSIGN:
      case QUESTIONMARK:
      case NUMBERSIGN:
      case EXCLAMATIONMARK:
        break;
      case LEFTCURLYBRACKET:
        code = scanner2.nextCharCode();
        if (code < 48 || code > 57) {
          return maybeToken(scanner2);
        }
        break;
      default:
        if (scanner2.isNameCharCode(code)) {
          return readKeywordOrFunction(scanner2);
        }
        return maybeToken(scanner2);
    }
  }
  function parse3(source) {
    const scanner$1 = new scanner.Scanner(source);
    const result = readImplicitGroup(scanner$1);
    if (scanner$1.pos !== source.length) {
      scanner$1.error("Unexpected input");
    }
    if (result.terms.length === 1 && result.terms[0].type === "Group") {
      return result.terms[0];
    }
    return result;
  }
  exports.parse = parse3;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/match-graph.cjs
var require_match_graph = __commonJS((exports) => {
  var parse3 = require_parse();
  var MATCH = { type: "Match" };
  var MISMATCH = { type: "Mismatch" };
  var DISALLOW_EMPTY = { type: "DisallowEmpty" };
  var LEFTPARENTHESIS = 40;
  var RIGHTPARENTHESIS = 41;
  function createCondition(match, thenBranch, elseBranch) {
    if (thenBranch === MATCH && elseBranch === MISMATCH) {
      return match;
    }
    if (match === MATCH && thenBranch === MATCH && elseBranch === MATCH) {
      return match;
    }
    if (match.type === "If" && match.else === MISMATCH && thenBranch === MATCH) {
      thenBranch = match.then;
      match = match.match;
    }
    return {
      type: "If",
      match,
      then: thenBranch,
      else: elseBranch
    };
  }
  function isFunctionType(name) {
    return name.length > 2 && name.charCodeAt(name.length - 2) === LEFTPARENTHESIS && name.charCodeAt(name.length - 1) === RIGHTPARENTHESIS;
  }
  function isEnumCapatible(term) {
    return term.type === "Keyword" || term.type === "AtKeyword" || term.type === "Function" || term.type === "Type" && isFunctionType(term.name);
  }
  function groupNode(terms, combinator = " ", explicit = false) {
    return {
      type: "Group",
      terms,
      combinator,
      disallowEmpty: false,
      explicit
    };
  }
  function replaceTypeInGraph(node2, replacements, visited = new Set) {
    if (!visited.has(node2)) {
      visited.add(node2);
      switch (node2.type) {
        case "If":
          node2.match = replaceTypeInGraph(node2.match, replacements, visited);
          node2.then = replaceTypeInGraph(node2.then, replacements, visited);
          node2.else = replaceTypeInGraph(node2.else, replacements, visited);
          break;
        case "Type":
          return replacements[node2.name] || node2;
      }
    }
    return node2;
  }
  function buildGroupMatchGraph(combinator, terms, atLeastOneTermMatched) {
    switch (combinator) {
      case " ": {
        let result = MATCH;
        for (let i = terms.length - 1;i >= 0; i--) {
          const term = terms[i];
          result = createCondition(term, result, MISMATCH);
        }
        return result;
      }
      case "|": {
        let result = MISMATCH;
        let map = null;
        for (let i = terms.length - 1;i >= 0; i--) {
          let term = terms[i];
          if (isEnumCapatible(term)) {
            if (map === null && i > 0 && isEnumCapatible(terms[i - 1])) {
              map = Object.create(null);
              result = createCondition({
                type: "Enum",
                map
              }, MATCH, result);
            }
            if (map !== null) {
              const key = (isFunctionType(term.name) ? term.name.slice(0, -1) : term.name).toLowerCase();
              if (key in map === false) {
                map[key] = term;
                continue;
              }
            }
          }
          map = null;
          result = createCondition(term, MATCH, result);
        }
        return result;
      }
      case "&&": {
        if (terms.length > 5) {
          return {
            type: "MatchOnce",
            terms,
            all: true
          };
        }
        let result = MISMATCH;
        for (let i = terms.length - 1;i >= 0; i--) {
          const term = terms[i];
          let thenClause;
          if (terms.length > 1) {
            thenClause = buildGroupMatchGraph(combinator, terms.filter(function(newGroupTerm) {
              return newGroupTerm !== term;
            }), false);
          } else {
            thenClause = MATCH;
          }
          result = createCondition(term, thenClause, result);
        }
        return result;
      }
      case "||": {
        if (terms.length > 5) {
          return {
            type: "MatchOnce",
            terms,
            all: false
          };
        }
        let result = atLeastOneTermMatched ? MATCH : MISMATCH;
        for (let i = terms.length - 1;i >= 0; i--) {
          const term = terms[i];
          let thenClause;
          if (terms.length > 1) {
            thenClause = buildGroupMatchGraph(combinator, terms.filter(function(newGroupTerm) {
              return newGroupTerm !== term;
            }), true);
          } else {
            thenClause = MATCH;
          }
          result = createCondition(term, thenClause, result);
        }
        return result;
      }
    }
  }
  function buildMultiplierMatchGraph(node2) {
    let result = MATCH;
    let matchTerm = buildMatchGraphInternal(node2.term);
    if (node2.max === 0) {
      matchTerm = createCondition(matchTerm, DISALLOW_EMPTY, MISMATCH);
      result = createCondition(matchTerm, null, MISMATCH);
      result.then = createCondition(MATCH, MATCH, result);
      if (node2.comma) {
        result.then.else = createCondition({ type: "Comma", syntax: node2 }, result, MISMATCH);
      }
    } else {
      for (let i = node2.min || 1;i <= node2.max; i++) {
        if (node2.comma && result !== MATCH) {
          result = createCondition({ type: "Comma", syntax: node2 }, result, MISMATCH);
        }
        result = createCondition(matchTerm, createCondition(MATCH, MATCH, result), MISMATCH);
      }
    }
    if (node2.min === 0) {
      result = createCondition(MATCH, MATCH, result);
    } else {
      for (let i = 0;i < node2.min - 1; i++) {
        if (node2.comma && result !== MATCH) {
          result = createCondition({ type: "Comma", syntax: node2 }, result, MISMATCH);
        }
        result = createCondition(matchTerm, result, MISMATCH);
      }
    }
    return result;
  }
  function buildMatchGraphInternal(node2) {
    if (typeof node2 === "function") {
      return {
        type: "Generic",
        fn: node2
      };
    }
    switch (node2.type) {
      case "Group": {
        let result = buildGroupMatchGraph(node2.combinator, node2.terms.map(buildMatchGraphInternal), false);
        if (node2.disallowEmpty) {
          result = createCondition(result, DISALLOW_EMPTY, MISMATCH);
        }
        return result;
      }
      case "Multiplier":
        return buildMultiplierMatchGraph(node2);
      case "Boolean": {
        const term = buildMatchGraphInternal(node2.term);
        const matchNode = buildMatchGraphInternal(groupNode([
          groupNode([
            { type: "Keyword", name: "not" },
            { type: "Type", name: "!boolean-group" }
          ]),
          groupNode([
            { type: "Type", name: "!boolean-group" },
            groupNode([
              { type: "Multiplier", comma: false, min: 0, max: 0, term: groupNode([
                { type: "Keyword", name: "and" },
                { type: "Type", name: "!boolean-group" }
              ]) },
              { type: "Multiplier", comma: false, min: 0, max: 0, term: groupNode([
                { type: "Keyword", name: "or" },
                { type: "Type", name: "!boolean-group" }
              ]) }
            ], "|")
          ])
        ], "|"));
        const booleanGroup = buildMatchGraphInternal(groupNode([
          { type: "Type", name: "!term" },
          groupNode([
            { type: "Token", value: "(" },
            { type: "Type", name: "!self" },
            { type: "Token", value: ")" }
          ]),
          { type: "Type", name: "general-enclosed" }
        ], "|"));
        replaceTypeInGraph(booleanGroup, { "!term": term, "!self": matchNode });
        replaceTypeInGraph(matchNode, { "!boolean-group": booleanGroup });
        return matchNode;
      }
      case "Type":
      case "Property":
        return {
          type: node2.type,
          name: node2.name,
          syntax: node2
        };
      case "Keyword":
        return {
          type: node2.type,
          name: node2.name.toLowerCase(),
          syntax: node2
        };
      case "AtKeyword":
        return {
          type: node2.type,
          name: "@" + node2.name.toLowerCase(),
          syntax: node2
        };
      case "Function":
        return {
          type: node2.type,
          name: node2.name.toLowerCase() + "(",
          syntax: node2
        };
      case "String":
        if (node2.value.length === 3) {
          return {
            type: "Token",
            value: node2.value.charAt(1),
            syntax: node2
          };
        }
        return {
          type: node2.type,
          value: node2.value.substr(1, node2.value.length - 2).replace(/\\'/g, "'"),
          syntax: node2
        };
      case "Token":
        return {
          type: node2.type,
          value: node2.value,
          syntax: node2
        };
      case "Comma":
        return {
          type: node2.type,
          syntax: node2
        };
      default:
        throw new Error("Unknown node type:", node2.type);
    }
  }
  function buildMatchGraph(syntaxTree, ref) {
    if (typeof syntaxTree === "string") {
      syntaxTree = parse3.parse(syntaxTree);
    }
    return {
      type: "MatchGraph",
      match: buildMatchGraphInternal(syntaxTree),
      syntax: ref || null,
      source: syntaxTree
    };
  }
  exports.DISALLOW_EMPTY = DISALLOW_EMPTY;
  exports.MATCH = MATCH;
  exports.MISMATCH = MISMATCH;
  exports.buildMatchGraph = buildMatchGraph;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/match.cjs
var require_match = __commonJS((exports) => {
  var matchGraph = require_match_graph();
  var types2 = require_types();
  var { hasOwnProperty: hasOwnProperty2 } = Object.prototype;
  var STUB = 0;
  var TOKEN = 1;
  var OPEN_SYNTAX = 2;
  var CLOSE_SYNTAX = 3;
  var EXIT_REASON_MATCH = "Match";
  var EXIT_REASON_MISMATCH = "Mismatch";
  var EXIT_REASON_ITERATION_LIMIT = "Maximum iteration number exceeded (please fill an issue on https://github.com/csstree/csstree/issues)";
  var ITERATION_LIMIT = 15000;
  function reverseList(list) {
    let prev = null;
    let next = null;
    let item = list;
    while (item !== null) {
      next = item.prev;
      item.prev = prev;
      prev = item;
      item = next;
    }
    return prev;
  }
  function areStringsEqualCaseInsensitive(testStr, referenceStr) {
    if (testStr.length !== referenceStr.length) {
      return false;
    }
    for (let i = 0;i < testStr.length; i++) {
      const referenceCode = referenceStr.charCodeAt(i);
      let testCode = testStr.charCodeAt(i);
      if (testCode >= 65 && testCode <= 90) {
        testCode = testCode | 32;
      }
      if (testCode !== referenceCode) {
        return false;
      }
    }
    return true;
  }
  function isContextEdgeDelim(token) {
    if (token.type !== types2.Delim) {
      return false;
    }
    return token.value !== "?";
  }
  function isCommaContextStart(token) {
    if (token === null) {
      return true;
    }
    return token.type === types2.Comma || token.type === types2.Function || token.type === types2.LeftParenthesis || token.type === types2.LeftSquareBracket || token.type === types2.LeftCurlyBracket || isContextEdgeDelim(token);
  }
  function isCommaContextEnd(token) {
    if (token === null) {
      return true;
    }
    return token.type === types2.RightParenthesis || token.type === types2.RightSquareBracket || token.type === types2.RightCurlyBracket || token.type === types2.Delim && token.value === "/";
  }
  function internalMatch(tokens, state, syntaxes) {
    function moveToNextToken() {
      do {
        tokenIndex++;
        token = tokenIndex < tokens.length ? tokens[tokenIndex] : null;
      } while (token !== null && (token.type === types2.WhiteSpace || token.type === types2.Comment));
    }
    function getNextToken(offset) {
      const nextIndex = tokenIndex + offset;
      return nextIndex < tokens.length ? tokens[nextIndex] : null;
    }
    function stateSnapshotFromSyntax(nextState, prev) {
      return {
        nextState,
        matchStack,
        syntaxStack,
        thenStack,
        tokenIndex,
        prev
      };
    }
    function pushThenStack(nextState) {
      thenStack = {
        nextState,
        matchStack,
        syntaxStack,
        prev: thenStack
      };
    }
    function pushElseStack(nextState) {
      elseStack = stateSnapshotFromSyntax(nextState, elseStack);
    }
    function addTokenToMatch() {
      matchStack = {
        type: TOKEN,
        syntax: state.syntax,
        token,
        prev: matchStack
      };
      moveToNextToken();
      syntaxStash = null;
      if (tokenIndex > longestMatch) {
        longestMatch = tokenIndex;
      }
    }
    function openSyntax() {
      syntaxStack = {
        syntax: state.syntax,
        opts: state.syntax.opts || syntaxStack !== null && syntaxStack.opts || null,
        prev: syntaxStack
      };
      matchStack = {
        type: OPEN_SYNTAX,
        syntax: state.syntax,
        token: matchStack.token,
        prev: matchStack
      };
    }
    function closeSyntax() {
      if (matchStack.type === OPEN_SYNTAX) {
        matchStack = matchStack.prev;
      } else {
        matchStack = {
          type: CLOSE_SYNTAX,
          syntax: syntaxStack.syntax,
          token: matchStack.token,
          prev: matchStack
        };
      }
      syntaxStack = syntaxStack.prev;
    }
    let syntaxStack = null;
    let thenStack = null;
    let elseStack = null;
    let syntaxStash = null;
    let iterationCount = 0;
    let exitReason = null;
    let token = null;
    let tokenIndex = -1;
    let longestMatch = 0;
    let matchStack = {
      type: STUB,
      syntax: null,
      token: null,
      prev: null
    };
    moveToNextToken();
    while (exitReason === null && ++iterationCount < ITERATION_LIMIT) {
      switch (state.type) {
        case "Match":
          if (thenStack === null) {
            if (token !== null) {
              if (tokenIndex !== tokens.length - 1 || token.value !== "\\0" && token.value !== "\\9") {
                state = matchGraph.MISMATCH;
                break;
              }
            }
            exitReason = EXIT_REASON_MATCH;
            break;
          }
          state = thenStack.nextState;
          if (state === matchGraph.DISALLOW_EMPTY) {
            if (thenStack.matchStack === matchStack) {
              state = matchGraph.MISMATCH;
              break;
            } else {
              state = matchGraph.MATCH;
            }
          }
          while (thenStack.syntaxStack !== syntaxStack) {
            closeSyntax();
          }
          thenStack = thenStack.prev;
          break;
        case "Mismatch":
          if (syntaxStash !== null && syntaxStash !== false) {
            if (elseStack === null || tokenIndex > elseStack.tokenIndex) {
              elseStack = syntaxStash;
              syntaxStash = false;
            }
          } else if (elseStack === null) {
            exitReason = EXIT_REASON_MISMATCH;
            break;
          }
          state = elseStack.nextState;
          thenStack = elseStack.thenStack;
          syntaxStack = elseStack.syntaxStack;
          matchStack = elseStack.matchStack;
          tokenIndex = elseStack.tokenIndex;
          token = tokenIndex < tokens.length ? tokens[tokenIndex] : null;
          elseStack = elseStack.prev;
          break;
        case "MatchGraph":
          state = state.match;
          break;
        case "If":
          if (state.else !== matchGraph.MISMATCH) {
            pushElseStack(state.else);
          }
          if (state.then !== matchGraph.MATCH) {
            pushThenStack(state.then);
          }
          state = state.match;
          break;
        case "MatchOnce":
          state = {
            type: "MatchOnceBuffer",
            syntax: state,
            index: 0,
            mask: 0
          };
          break;
        case "MatchOnceBuffer": {
          const terms = state.syntax.terms;
          if (state.index === terms.length) {
            if (state.mask === 0 || state.syntax.all) {
              state = matchGraph.MISMATCH;
              break;
            }
            state = matchGraph.MATCH;
            break;
          }
          if (state.mask === (1 << terms.length) - 1) {
            state = matchGraph.MATCH;
            break;
          }
          for (;state.index < terms.length; state.index++) {
            const matchFlag = 1 << state.index;
            if ((state.mask & matchFlag) === 0) {
              pushElseStack(state);
              pushThenStack({
                type: "AddMatchOnce",
                syntax: state.syntax,
                mask: state.mask | matchFlag
              });
              state = terms[state.index++];
              break;
            }
          }
          break;
        }
        case "AddMatchOnce":
          state = {
            type: "MatchOnceBuffer",
            syntax: state.syntax,
            index: 0,
            mask: state.mask
          };
          break;
        case "Enum":
          if (token !== null) {
            let name = token.value.toLowerCase();
            if (name.indexOf("\\") !== -1) {
              name = name.replace(/\\[09].*$/, "");
            }
            if (hasOwnProperty2.call(state.map, name)) {
              state = state.map[name];
              break;
            }
          }
          state = matchGraph.MISMATCH;
          break;
        case "Generic": {
          const opts = syntaxStack !== null ? syntaxStack.opts : null;
          const lastTokenIndex2 = tokenIndex + Math.floor(state.fn(token, getNextToken, opts));
          if (!isNaN(lastTokenIndex2) && lastTokenIndex2 > tokenIndex) {
            while (tokenIndex < lastTokenIndex2) {
              addTokenToMatch();
            }
            state = matchGraph.MATCH;
          } else {
            state = matchGraph.MISMATCH;
          }
          break;
        }
        case "Type":
        case "Property": {
          const syntaxDict = state.type === "Type" ? "types" : "properties";
          const dictSyntax = hasOwnProperty2.call(syntaxes, syntaxDict) ? syntaxes[syntaxDict][state.name] : null;
          if (!dictSyntax || !dictSyntax.match) {
            throw new Error("Bad syntax reference: " + (state.type === "Type" ? "<" + state.name + ">" : "<'" + state.name + "'>"));
          }
          if (syntaxStash !== false && token !== null && state.type === "Type") {
            const lowPriorityMatching = state.name === "custom-ident" && token.type === types2.Ident || state.name === "length" && token.value === "0";
            if (lowPriorityMatching) {
              if (syntaxStash === null) {
                syntaxStash = stateSnapshotFromSyntax(state, elseStack);
              }
              state = matchGraph.MISMATCH;
              break;
            }
          }
          openSyntax();
          state = dictSyntax.matchRef || dictSyntax.match;
          break;
        }
        case "Keyword": {
          const name = state.name;
          if (token !== null) {
            let keywordName = token.value;
            if (keywordName.indexOf("\\") !== -1) {
              keywordName = keywordName.replace(/\\[09].*$/, "");
            }
            if (areStringsEqualCaseInsensitive(keywordName, name)) {
              addTokenToMatch();
              state = matchGraph.MATCH;
              break;
            }
          }
          state = matchGraph.MISMATCH;
          break;
        }
        case "AtKeyword":
        case "Function":
          if (token !== null && areStringsEqualCaseInsensitive(token.value, state.name)) {
            addTokenToMatch();
            state = matchGraph.MATCH;
            break;
          }
          state = matchGraph.MISMATCH;
          break;
        case "Token":
          if (token !== null && token.value === state.value) {
            addTokenToMatch();
            state = matchGraph.MATCH;
            break;
          }
          state = matchGraph.MISMATCH;
          break;
        case "Comma":
          if (token !== null && token.type === types2.Comma) {
            if (isCommaContextStart(matchStack.token)) {
              state = matchGraph.MISMATCH;
            } else {
              addTokenToMatch();
              state = isCommaContextEnd(token) ? matchGraph.MISMATCH : matchGraph.MATCH;
            }
          } else {
            state = isCommaContextStart(matchStack.token) || isCommaContextEnd(token) ? matchGraph.MATCH : matchGraph.MISMATCH;
          }
          break;
        case "String":
          let string = "";
          let lastTokenIndex = tokenIndex;
          for (;lastTokenIndex < tokens.length && string.length < state.value.length; lastTokenIndex++) {
            string += tokens[lastTokenIndex].value;
          }
          if (areStringsEqualCaseInsensitive(string, state.value)) {
            while (tokenIndex < lastTokenIndex) {
              addTokenToMatch();
            }
            state = matchGraph.MATCH;
          } else {
            state = matchGraph.MISMATCH;
          }
          break;
        default:
          throw new Error("Unknown node type: " + state.type);
      }
    }
    switch (exitReason) {
      case null:
        console.warn("[csstree-match] BREAK after " + ITERATION_LIMIT + " iterations");
        exitReason = EXIT_REASON_ITERATION_LIMIT;
        matchStack = null;
        break;
      case EXIT_REASON_MATCH:
        while (syntaxStack !== null) {
          closeSyntax();
        }
        break;
      default:
        matchStack = null;
    }
    return {
      tokens,
      reason: exitReason,
      iterations: iterationCount,
      match: matchStack,
      longestMatch
    };
  }
  function matchAsList(tokens, matchGraph2, syntaxes) {
    const matchResult = internalMatch(tokens, matchGraph2, syntaxes || {});
    if (matchResult.match !== null) {
      let item = reverseList(matchResult.match).prev;
      matchResult.match = [];
      while (item !== null) {
        switch (item.type) {
          case OPEN_SYNTAX:
          case CLOSE_SYNTAX:
            matchResult.match.push({
              type: item.type,
              syntax: item.syntax
            });
            break;
          default:
            matchResult.match.push({
              token: item.token.value,
              node: item.token.node
            });
            break;
        }
        item = item.prev;
      }
    }
    return matchResult;
  }
  function matchAsTree(tokens, matchGraph2, syntaxes) {
    const matchResult = internalMatch(tokens, matchGraph2, syntaxes || {});
    if (matchResult.match === null) {
      return matchResult;
    }
    let item = matchResult.match;
    let host = matchResult.match = {
      syntax: matchGraph2.syntax || null,
      match: []
    };
    const hostStack = [host];
    item = reverseList(item).prev;
    while (item !== null) {
      switch (item.type) {
        case OPEN_SYNTAX:
          host.match.push(host = {
            syntax: item.syntax,
            match: []
          });
          hostStack.push(host);
          break;
        case CLOSE_SYNTAX:
          hostStack.pop();
          host = hostStack[hostStack.length - 1];
          break;
        default:
          host.match.push({
            syntax: item.syntax || null,
            token: item.token.value,
            node: item.token.node
          });
      }
      item = item.prev;
    }
    return matchResult;
  }
  exports.matchAsList = matchAsList;
  exports.matchAsTree = matchAsTree;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/trace.cjs
var require_trace = __commonJS((exports) => {
  function getTrace(node2) {
    function shouldPutToTrace(syntax) {
      if (syntax === null) {
        return false;
      }
      return syntax.type === "Type" || syntax.type === "Property" || syntax.type === "Keyword";
    }
    function hasMatch(matchNode) {
      if (Array.isArray(matchNode.match)) {
        for (let i = 0;i < matchNode.match.length; i++) {
          if (hasMatch(matchNode.match[i])) {
            if (shouldPutToTrace(matchNode.syntax)) {
              result.unshift(matchNode.syntax);
            }
            return true;
          }
        }
      } else if (matchNode.node === node2) {
        result = shouldPutToTrace(matchNode.syntax) ? [matchNode.syntax] : [];
        return true;
      }
      return false;
    }
    let result = null;
    if (this.matched !== null) {
      hasMatch(this.matched);
    }
    return result;
  }
  function isType(node2, type) {
    return testNode(this, node2, (match) => match.type === "Type" && match.name === type);
  }
  function isProperty(node2, property) {
    return testNode(this, node2, (match) => match.type === "Property" && match.name === property);
  }
  function isKeyword(node2) {
    return testNode(this, node2, (match) => match.type === "Keyword");
  }
  function testNode(match, node2, fn) {
    const trace = getTrace.call(match, node2);
    if (trace === null) {
      return false;
    }
    return trace.some(fn);
  }
  exports.getTrace = getTrace;
  exports.isKeyword = isKeyword;
  exports.isProperty = isProperty;
  exports.isType = isType;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/search.cjs
var require_search = __commonJS((exports) => {
  var List = require_List();
  function getFirstMatchNode(matchNode) {
    if ("node" in matchNode) {
      return matchNode.node;
    }
    return getFirstMatchNode(matchNode.match[0]);
  }
  function getLastMatchNode(matchNode) {
    if ("node" in matchNode) {
      return matchNode.node;
    }
    return getLastMatchNode(matchNode.match[matchNode.match.length - 1]);
  }
  function matchFragments(lexer, ast, match, type, name) {
    function findFragments(matchNode) {
      if (matchNode.syntax !== null && matchNode.syntax.type === type && matchNode.syntax.name === name) {
        const start = getFirstMatchNode(matchNode);
        const end = getLastMatchNode(matchNode);
        lexer.syntax.walk(ast, function(node2, item, list) {
          if (node2 === start) {
            const nodes = new List.List;
            do {
              nodes.appendData(item.data);
              if (item.data === end) {
                break;
              }
              item = item.next;
            } while (item !== null);
            fragments.push({
              parent: list,
              nodes
            });
          }
        });
      }
      if (Array.isArray(matchNode.match)) {
        matchNode.match.forEach(findFragments);
      }
    }
    const fragments = [];
    if (match.matched !== null) {
      findFragments(match.matched);
    }
    return fragments;
  }
  exports.matchFragments = matchFragments;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/structure.cjs
var require_structure = __commonJS((exports) => {
  var List = require_List();
  var { hasOwnProperty: hasOwnProperty2 } = Object.prototype;
  function isValidNumber(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0;
  }
  function isValidLocation(loc) {
    return Boolean(loc) && isValidNumber(loc.offset) && isValidNumber(loc.line) && isValidNumber(loc.column);
  }
  function createNodeStructureChecker(type, fields) {
    return function checkNode(node2, warn) {
      if (!node2 || node2.constructor !== Object) {
        return warn(node2, "Type of node should be an Object");
      }
      for (let key in node2) {
        let valid = true;
        if (hasOwnProperty2.call(node2, key) === false) {
          continue;
        }
        if (key === "type") {
          if (node2.type !== type) {
            warn(node2, "Wrong node type `" + node2.type + "`, expected `" + type + "`");
          }
        } else if (key === "loc") {
          if (node2.loc === null) {
            continue;
          } else if (node2.loc && node2.loc.constructor === Object) {
            if (typeof node2.loc.source !== "string") {
              key += ".source";
            } else if (!isValidLocation(node2.loc.start)) {
              key += ".start";
            } else if (!isValidLocation(node2.loc.end)) {
              key += ".end";
            } else {
              continue;
            }
          }
          valid = false;
        } else if (fields.hasOwnProperty(key)) {
          valid = false;
          for (let i = 0;!valid && i < fields[key].length; i++) {
            const fieldType = fields[key][i];
            switch (fieldType) {
              case String:
                valid = typeof node2[key] === "string";
                break;
              case Boolean:
                valid = typeof node2[key] === "boolean";
                break;
              case null:
                valid = node2[key] === null;
                break;
              default:
                if (typeof fieldType === "string") {
                  valid = node2[key] && node2[key].type === fieldType;
                } else if (Array.isArray(fieldType)) {
                  valid = node2[key] instanceof List.List;
                }
            }
          }
        } else {
          warn(node2, "Unknown field `" + key + "` for " + type + " node type");
        }
        if (!valid) {
          warn(node2, "Bad value for `" + type + "." + key + "`");
        }
      }
      for (const key in fields) {
        if (hasOwnProperty2.call(fields, key) && hasOwnProperty2.call(node2, key) === false) {
          warn(node2, "Field `" + type + "." + key + "` is missed");
        }
      }
    };
  }
  function genTypesList(fieldTypes, path) {
    const docsTypes = [];
    for (let i = 0;i < fieldTypes.length; i++) {
      const fieldType = fieldTypes[i];
      if (fieldType === String || fieldType === Boolean) {
        docsTypes.push(fieldType.name.toLowerCase());
      } else if (fieldType === null) {
        docsTypes.push("null");
      } else if (typeof fieldType === "string") {
        docsTypes.push(fieldType);
      } else if (Array.isArray(fieldType)) {
        docsTypes.push("List<" + (genTypesList(fieldType, path) || "any") + ">");
      } else {
        throw new Error("Wrong value `" + fieldType + "` in `" + path + "` structure definition");
      }
    }
    return docsTypes.join(" | ");
  }
  function processStructure(name, nodeType) {
    const structure = nodeType.structure;
    const fields = {
      type: String,
      loc: true
    };
    const docs = {
      type: '"' + name + '"'
    };
    for (const key in structure) {
      if (hasOwnProperty2.call(structure, key) === false) {
        continue;
      }
      const fieldTypes = fields[key] = Array.isArray(structure[key]) ? structure[key].slice() : [structure[key]];
      docs[key] = genTypesList(fieldTypes, name + "." + key);
    }
    return {
      docs,
      check: createNodeStructureChecker(name, fields)
    };
  }
  function getStructureFromConfig(config) {
    const structure = {};
    if (config.node) {
      for (const name in config.node) {
        if (hasOwnProperty2.call(config.node, name)) {
          const nodeType = config.node[name];
          if (nodeType.structure) {
            structure[name] = processStructure(name, nodeType);
          } else {
            throw new Error("Missed `structure` field in `" + name + "` node type definition");
          }
        }
      }
    }
    return structure;
  }
  exports.getStructureFromConfig = getStructureFromConfig;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/walk.cjs
var require_walk = __commonJS((exports) => {
  var noop = function() {};
  function ensureFunction(value) {
    return typeof value === "function" ? value : noop;
  }
  function walk(node2, options, context) {
    function walk2(node3) {
      enter.call(context, node3);
      switch (node3.type) {
        case "Group":
          node3.terms.forEach(walk2);
          break;
        case "Multiplier":
        case "Boolean":
          walk2(node3.term);
          break;
        case "Type":
        case "Property":
        case "Keyword":
        case "AtKeyword":
        case "Function":
        case "String":
        case "Token":
        case "Comma":
          break;
        default:
          throw new Error("Unknown type: " + node3.type);
      }
      leave.call(context, node3);
    }
    let enter = noop;
    let leave = noop;
    if (typeof options === "function") {
      enter = options;
    } else if (options) {
      enter = ensureFunction(options.enter);
      leave = ensureFunction(options.leave);
    }
    if (enter === noop && leave === noop) {
      throw new Error("Neither `enter` nor `leave` walker handler is set or both aren't a function");
    }
    walk2(node2);
  }
  exports.walk = walk;
});

// ../imp-pinned/node_modules/css-tree/cjs/lexer/Lexer.cjs
var require_Lexer = __commonJS((exports) => {
  var error = require_error();
  var names = require_names2();
  var genericConst = require_generic_const();
  var generic = require_generic();
  var units = require_units();
  var prepareTokens = require_prepare_tokens();
  var matchGraph = require_match_graph();
  var match = require_match();
  var trace = require_trace();
  var search = require_search();
  var structure = require_structure();
  var parse3 = require_parse();
  var generate2 = require_generate();
  var walk = require_walk();
  function dumpMapSyntax(map, compact, syntaxAsAst) {
    const result = {};
    for (const name in map) {
      if (map[name].syntax) {
        result[name] = syntaxAsAst ? map[name].syntax : generate2.generate(map[name].syntax, { compact });
      }
    }
    return result;
  }
  function dumpAtruleMapSyntax(map, compact, syntaxAsAst) {
    const result = {};
    for (const [name, atrule] of Object.entries(map)) {
      result[name] = {
        prelude: atrule.prelude && (syntaxAsAst ? atrule.prelude.syntax : generate2.generate(atrule.prelude.syntax, { compact })),
        descriptors: atrule.descriptors && dumpMapSyntax(atrule.descriptors, compact, syntaxAsAst)
      };
    }
    return result;
  }
  function valueHasVar(tokens) {
    for (let i = 0;i < tokens.length; i++) {
      if (tokens[i].value.toLowerCase() === "var(") {
        return true;
      }
    }
    return false;
  }
  function syntaxHasTopLevelCommaMultiplier(syntax) {
    const singleTerm = syntax.terms[0];
    return syntax.explicit === false && syntax.terms.length === 1 && singleTerm.type === "Multiplier" && singleTerm.comma === true;
  }
  function buildMatchResult(matched, error2, iterations) {
    return {
      matched,
      iterations,
      error: error2,
      ...trace
    };
  }
  function matchSyntax(lexer, syntax, value, useCssWideKeywords) {
    const tokens = prepareTokens(value, lexer.syntax);
    let result;
    if (valueHasVar(tokens)) {
      return buildMatchResult(null, new Error("Matching for a tree with var() is not supported"));
    }
    if (useCssWideKeywords) {
      result = match.matchAsTree(tokens, lexer.cssWideKeywordsSyntax, lexer);
    }
    if (!useCssWideKeywords || !result.match) {
      result = match.matchAsTree(tokens, syntax.match, lexer);
      if (!result.match) {
        return buildMatchResult(null, new error.SyntaxMatchError(result.reason, syntax.syntax, value, result), result.iterations);
      }
    }
    return buildMatchResult(result.match, null, result.iterations);
  }

  class Lexer {
    constructor(config, syntax, structure$1) {
      this.cssWideKeywords = genericConst.cssWideKeywords;
      this.syntax = syntax;
      this.generic = false;
      this.units = { ...units };
      this.atrules = Object.create(null);
      this.properties = Object.create(null);
      this.types = Object.create(null);
      this.structure = structure$1 || structure.getStructureFromConfig(config);
      if (config) {
        if (config.cssWideKeywords) {
          this.cssWideKeywords = config.cssWideKeywords;
        }
        if (config.units) {
          for (const group of Object.keys(units)) {
            if (Array.isArray(config.units[group])) {
              this.units[group] = config.units[group];
            }
          }
        }
        if (config.types) {
          for (const [name, type] of Object.entries(config.types)) {
            this.addType_(name, type);
          }
        }
        if (config.generic) {
          this.generic = true;
          for (const [name, value] of Object.entries(generic.createGenericTypes(this.units))) {
            this.addType_(name, value);
          }
        }
        if (config.atrules) {
          for (const [name, atrule] of Object.entries(config.atrules)) {
            this.addAtrule_(name, atrule);
          }
        }
        if (config.properties) {
          for (const [name, property] of Object.entries(config.properties)) {
            this.addProperty_(name, property);
          }
        }
      }
      this.cssWideKeywordsSyntax = matchGraph.buildMatchGraph(this.cssWideKeywords.join(" |  "));
    }
    checkStructure(ast) {
      function collectWarning(node2, message) {
        warns.push({ node: node2, message });
      }
      const structure2 = this.structure;
      const warns = [];
      this.syntax.walk(ast, function(node2) {
        if (structure2.hasOwnProperty(node2.type)) {
          structure2[node2.type].check(node2, collectWarning);
        } else {
          collectWarning(node2, "Unknown node type `" + node2.type + "`");
        }
      });
      return warns.length ? warns : false;
    }
    createDescriptor(syntax, type, name, parent = null) {
      const ref = {
        type,
        name
      };
      const descriptor = {
        type,
        name,
        parent,
        serializable: typeof syntax === "string" || syntax && typeof syntax.type === "string",
        syntax: null,
        match: null,
        matchRef: null
      };
      if (typeof syntax === "function") {
        descriptor.match = matchGraph.buildMatchGraph(syntax, ref);
      } else {
        if (typeof syntax === "string") {
          Object.defineProperty(descriptor, "syntax", {
            get() {
              Object.defineProperty(descriptor, "syntax", {
                value: parse3.parse(syntax)
              });
              return descriptor.syntax;
            }
          });
        } else {
          descriptor.syntax = syntax;
        }
        Object.defineProperty(descriptor, "match", {
          get() {
            Object.defineProperty(descriptor, "match", {
              value: matchGraph.buildMatchGraph(descriptor.syntax, ref)
            });
            return descriptor.match;
          }
        });
        if (type === "Property") {
          Object.defineProperty(descriptor, "matchRef", {
            get() {
              const syntax2 = descriptor.syntax;
              const value = syntaxHasTopLevelCommaMultiplier(syntax2) ? matchGraph.buildMatchGraph({
                ...syntax2,
                terms: [syntax2.terms[0].term]
              }, ref) : null;
              Object.defineProperty(descriptor, "matchRef", {
                value
              });
              return value;
            }
          });
        }
      }
      return descriptor;
    }
    addAtrule_(name, syntax) {
      if (!syntax) {
        return;
      }
      this.atrules[name] = {
        type: "Atrule",
        name,
        prelude: syntax.prelude ? this.createDescriptor(syntax.prelude, "AtrulePrelude", name) : null,
        descriptors: syntax.descriptors ? Object.keys(syntax.descriptors).reduce((map, descName) => {
          map[descName] = this.createDescriptor(syntax.descriptors[descName], "AtruleDescriptor", descName, name);
          return map;
        }, Object.create(null)) : null
      };
    }
    addProperty_(name, syntax) {
      if (!syntax) {
        return;
      }
      this.properties[name] = this.createDescriptor(syntax, "Property", name);
    }
    addType_(name, syntax) {
      if (!syntax) {
        return;
      }
      this.types[name] = this.createDescriptor(syntax, "Type", name);
    }
    checkAtruleName(atruleName) {
      if (!this.getAtrule(atruleName)) {
        return new error.SyntaxReferenceError("Unknown at-rule", "@" + atruleName);
      }
    }
    checkAtrulePrelude(atruleName, prelude) {
      const error2 = this.checkAtruleName(atruleName);
      if (error2) {
        return error2;
      }
      const atrule = this.getAtrule(atruleName);
      if (!atrule.prelude && prelude) {
        return new SyntaxError("At-rule `@" + atruleName + "` should not contain a prelude");
      }
      if (atrule.prelude && !prelude) {
        if (!matchSyntax(this, atrule.prelude, "", false).matched) {
          return new SyntaxError("At-rule `@" + atruleName + "` should contain a prelude");
        }
      }
    }
    checkAtruleDescriptorName(atruleName, descriptorName) {
      const error$1 = this.checkAtruleName(atruleName);
      if (error$1) {
        return error$1;
      }
      const atrule = this.getAtrule(atruleName);
      const descriptor = names.keyword(descriptorName);
      if (!atrule.descriptors) {
        return new SyntaxError("At-rule `@" + atruleName + "` has no known descriptors");
      }
      if (!atrule.descriptors[descriptor.name] && !atrule.descriptors[descriptor.basename]) {
        return new error.SyntaxReferenceError("Unknown at-rule descriptor", descriptorName);
      }
    }
    checkPropertyName(propertyName) {
      if (!this.getProperty(propertyName)) {
        return new error.SyntaxReferenceError("Unknown property", propertyName);
      }
    }
    matchAtrulePrelude(atruleName, prelude) {
      const error2 = this.checkAtrulePrelude(atruleName, prelude);
      if (error2) {
        return buildMatchResult(null, error2);
      }
      const atrule = this.getAtrule(atruleName);
      if (!atrule.prelude) {
        return buildMatchResult(null, null);
      }
      return matchSyntax(this, atrule.prelude, prelude || "", false);
    }
    matchAtruleDescriptor(atruleName, descriptorName, value) {
      const error2 = this.checkAtruleDescriptorName(atruleName, descriptorName);
      if (error2) {
        return buildMatchResult(null, error2);
      }
      const atrule = this.getAtrule(atruleName);
      const descriptor = names.keyword(descriptorName);
      return matchSyntax(this, atrule.descriptors[descriptor.name] || atrule.descriptors[descriptor.basename], value, false);
    }
    matchDeclaration(node2) {
      if (node2.type !== "Declaration") {
        return buildMatchResult(null, new Error("Not a Declaration node"));
      }
      return this.matchProperty(node2.property, node2.value);
    }
    matchProperty(propertyName, value) {
      if (names.property(propertyName).custom) {
        return buildMatchResult(null, new Error("Lexer matching doesn't applicable for custom properties"));
      }
      const error2 = this.checkPropertyName(propertyName);
      if (error2) {
        return buildMatchResult(null, error2);
      }
      return matchSyntax(this, this.getProperty(propertyName), value, true);
    }
    matchType(typeName, value) {
      const typeSyntax = this.getType(typeName);
      if (!typeSyntax) {
        return buildMatchResult(null, new error.SyntaxReferenceError("Unknown type", typeName));
      }
      return matchSyntax(this, typeSyntax, value, false);
    }
    match(syntax, value) {
      if (typeof syntax !== "string" && (!syntax || !syntax.type)) {
        return buildMatchResult(null, new error.SyntaxReferenceError("Bad syntax"));
      }
      if (typeof syntax === "string" || !syntax.match) {
        syntax = this.createDescriptor(syntax, "Type", "anonymous");
      }
      return matchSyntax(this, syntax, value, false);
    }
    findValueFragments(propertyName, value, type, name) {
      return search.matchFragments(this, value, this.matchProperty(propertyName, value), type, name);
    }
    findDeclarationValueFragments(declaration, type, name) {
      return search.matchFragments(this, declaration.value, this.matchDeclaration(declaration), type, name);
    }
    findAllFragments(ast, type, name) {
      const result = [];
      this.syntax.walk(ast, {
        visit: "Declaration",
        enter: (declaration) => {
          result.push.apply(result, this.findDeclarationValueFragments(declaration, type, name));
        }
      });
      return result;
    }
    getAtrule(atruleName, fallbackBasename = true) {
      const atrule = names.keyword(atruleName);
      const atruleEntry = atrule.vendor && fallbackBasename ? this.atrules[atrule.name] || this.atrules[atrule.basename] : this.atrules[atrule.name];
      return atruleEntry || null;
    }
    getAtrulePrelude(atruleName, fallbackBasename = true) {
      const atrule = this.getAtrule(atruleName, fallbackBasename);
      return atrule && atrule.prelude || null;
    }
    getAtruleDescriptor(atruleName, name) {
      return this.atrules.hasOwnProperty(atruleName) && this.atrules.declarators ? this.atrules[atruleName].declarators[name] || null : null;
    }
    getProperty(propertyName, fallbackBasename = true) {
      const property = names.property(propertyName);
      const propertyEntry = property.vendor && fallbackBasename ? this.properties[property.name] || this.properties[property.basename] : this.properties[property.name];
      return propertyEntry || null;
    }
    getType(name) {
      return hasOwnProperty.call(this.types, name) ? this.types[name] : null;
    }
    validate() {
      function syntaxRef(name, isType) {
        return isType ? `<${name}>` : `<'${name}'>`;
      }
      function validate(syntax, name, broken, descriptor) {
        if (broken.has(name)) {
          return broken.get(name);
        }
        broken.set(name, false);
        if (descriptor.syntax !== null) {
          walk.walk(descriptor.syntax, function(node2) {
            if (node2.type !== "Type" && node2.type !== "Property") {
              return;
            }
            const map = node2.type === "Type" ? syntax.types : syntax.properties;
            const brokenMap = node2.type === "Type" ? brokenTypes : brokenProperties;
            if (!hasOwnProperty.call(map, node2.name)) {
              errors.push(`${syntaxRef(name, broken === brokenTypes)} used missed syntax definition ${syntaxRef(node2.name, node2.type === "Type")}`);
              broken.set(name, true);
            } else if (validate(syntax, node2.name, brokenMap, map[node2.name])) {
              errors.push(`${syntaxRef(name, broken === brokenTypes)} used broken syntax definition ${syntaxRef(node2.name, node2.type === "Type")}`);
              broken.set(name, true);
            }
          }, this);
        }
      }
      const errors = [];
      let brokenTypes = new Map;
      let brokenProperties = new Map;
      for (const key in this.types) {
        validate(this, key, brokenTypes, this.types[key]);
      }
      for (const key in this.properties) {
        validate(this, key, brokenProperties, this.properties[key]);
      }
      const brokenTypesArray = [...brokenTypes.keys()].filter((name) => brokenTypes.get(name));
      const brokenPropertiesArray = [...brokenProperties.keys()].filter((name) => brokenProperties.get(name));
      if (brokenTypesArray.length || brokenPropertiesArray.length) {
        return {
          errors,
          types: brokenTypesArray,
          properties: brokenPropertiesArray
        };
      }
      return null;
    }
    dump(syntaxAsAst, pretty) {
      return {
        generic: this.generic,
        cssWideKeywords: this.cssWideKeywords,
        units: this.units,
        types: dumpMapSyntax(this.types, !pretty, syntaxAsAst),
        properties: dumpMapSyntax(this.properties, !pretty, syntaxAsAst),
        atrules: dumpAtruleMapSyntax(this.atrules, !pretty, syntaxAsAst)
      };
    }
    toString() {
      return JSON.stringify(this.dump());
    }
  }
  exports.Lexer = Lexer;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/config/mix.cjs
var require_mix = __commonJS((exports, module) => {
  function appendOrSet(a, b) {
    if (typeof b === "string" && /^\s*\|/.test(b)) {
      return typeof a === "string" ? a + b : b.replace(/^\s*\|\s*/, "");
    }
    return b || null;
  }
  function extractProps(obj, props) {
    const result = Object.create(null);
    for (const prop of Object.keys(obj)) {
      if (props.includes(prop)) {
        result[prop] = obj[prop];
      }
    }
    return result;
  }
  function mergeDicts(base, ext, fields) {
    const result = { ...base };
    for (const [key, props] of Object.entries(ext)) {
      result[key] = {
        ...result[key],
        ...fields ? extractProps(props, fields) : props
      };
    }
    return result;
  }
  function mix(dest, src) {
    const result = { ...dest };
    for (const [prop, value] of Object.entries(src)) {
      switch (prop) {
        case "generic":
          result[prop] = Boolean(value);
          break;
        case "cssWideKeywords":
          result[prop] = dest[prop] ? [...dest[prop], ...value] : value || [];
          break;
        case "units":
          result[prop] = { ...dest[prop] };
          for (const [name, patch] of Object.entries(value)) {
            result[prop][name] = Array.isArray(patch) ? patch : [];
          }
          break;
        case "atrules":
          result[prop] = { ...dest[prop] };
          for (const [name, atrule] of Object.entries(value)) {
            const exists = result[prop][name] || {};
            const current = result[prop][name] = {
              prelude: exists.prelude || null,
              descriptors: {
                ...exists.descriptors
              }
            };
            if (!atrule) {
              continue;
            }
            current.prelude = atrule.prelude ? appendOrSet(current.prelude, atrule.prelude) : current.prelude || null;
            for (const [descriptorName, descriptorValue] of Object.entries(atrule.descriptors || {})) {
              current.descriptors[descriptorName] = descriptorValue ? appendOrSet(current.descriptors[descriptorName], descriptorValue) : null;
            }
            if (!Object.keys(current.descriptors).length) {
              current.descriptors = null;
            }
          }
          break;
        case "types":
        case "properties":
          result[prop] = { ...dest[prop] };
          for (const [name, syntax] of Object.entries(value)) {
            result[prop][name] = appendOrSet(result[prop][name], syntax);
          }
          break;
        case "parseContext":
          result[prop] = {
            ...dest[prop],
            ...value
          };
          break;
        case "scope":
        case "features":
          result[prop] = mergeDicts(dest[prop], value);
          break;
        case "atrule":
        case "pseudo":
          result[prop] = mergeDicts(dest[prop], value, ["parse"]);
          break;
        case "node":
          result[prop] = mergeDicts(dest[prop], value, ["name", "structure", "parse", "generate", "walkContext"]);
          break;
      }
    }
    return result;
  }
  module.exports = mix;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/create.cjs
var require_create5 = __commonJS((exports, module) => {
  var index = require_tokenizer();
  var create = require_create();
  var create$2 = require_create2();
  var create$3 = require_create3();
  var create$1 = require_create4();
  var Lexer = require_Lexer();
  var mix = require_mix();
  function createSyntax(config) {
    const parse3 = create.createParser(config);
    const walk = create$1.createWalker(config);
    const generate2 = create$2.createGenerator(config);
    const { fromPlainObject, toPlainObject } = create$3.createConvertor(walk);
    const syntax = {
      lexer: null,
      createLexer: (config2) => new Lexer.Lexer(config2, syntax, syntax.lexer.structure),
      tokenize: index.tokenize,
      parse: parse3,
      generate: generate2,
      walk,
      find: walk.find,
      findLast: walk.findLast,
      findAll: walk.findAll,
      fromPlainObject,
      toPlainObject,
      fork(extension) {
        const base = mix({}, config);
        return createSyntax(typeof extension === "function" ? extension(base) : mix(base, extension));
      }
    };
    syntax.lexer = new Lexer.Lexer({
      generic: config.generic,
      cssWideKeywords: config.cssWideKeywords,
      units: config.units,
      types: config.types,
      atrules: config.atrules,
      properties: config.properties,
      node: config.node
    }, syntax);
    return syntax;
  }
  var createSyntax$1 = (config) => createSyntax(mix({}, config));
  module.exports = createSyntax$1;
});

// ../imp-pinned/node_modules/css-tree/data/patch.json
var require_patch = __commonJS((exports, module) => {
  module.exports = {
    atrules: {
      charset: {
        prelude: "<string>"
      },
      container: {
        prelude: "[ <container-name> ]? <container-condition>"
      },
      "font-face": {
        descriptors: {
          "unicode-range": {
            comment: "replaces <unicode-range>, an old production name",
            syntax: "<urange>#"
          }
        }
      },
      "font-features-values": {
        comment: "The features values syntax is defined in https://www.w3.org/TR/css-fonts-4/#at-ruledef-font-feature-values",
        prelude: "[<string> | <custom-ident>]+",
        descriptors: {
          "font-display": "auto | block | swap | fallback | optional"
        }
      },
      scope: {
        prelude: "[ ( <scope-start> ) ]? [ to ( <scope-end> ) ]?"
      },
      "position-try": {
        comment: "The list of descriptors: https://developer.mozilla.org/en-US/docs/Web/CSS/@position-try",
        descriptors: {
          top: "<'top'>",
          left: "<'left'>",
          bottom: "<'bottom'>",
          right: "<'right'>",
          "inset-block-start": "<'inset-block-start'>",
          "inset-block-end": "<'inset-block-end'>",
          "inset-inline-start": "<'inset-inline-start'>",
          "inset-inline-end": "<'inset-inline-end'>",
          "inset-block": "<'inset-block'>",
          "inset-inline": "<'inset-inline'>",
          inset: "<'inset'>",
          "margin-top": "<'margin-top'>",
          "margin-left": "<'margin-left'>",
          "margin-bottom": "<'margin-bottom'>",
          "margin-right": "<'margin-right'>",
          "margin-block-start": "<'margin-block-start'>",
          "margin-block-end": "<'margin-block-end'>",
          "margin-inline-start": "<'margin-inline-start'>",
          "margin-inline-end": "<'margin-inline-end'>",
          margin: "<'margin'>",
          "margin-block": "<'margin-block'>",
          "margin-inline": "<'margin-inline'>",
          width: "<'width'>",
          height: "<'height'>",
          "min-width": "<'min-width'>",
          "min-height": "<'min-height'>",
          "max-width": "<'max-width'>",
          "max-height": "<'max-height'>",
          "block-size": "<'block-size'>",
          "inline-size": "<'inline-size'>",
          "min-block-size": "<'min-block-size'>",
          "min-inline-size": "<'min-inline-size'>",
          "max-block-size": "<'max-block-size'>",
          "max-inline-size": "<'max-inline-size'>",
          "align-self": "<'align-self'> | anchor-center",
          "justify-self": "<'justify-self'> | anchor-center"
        }
      }
    },
    properties: {
      "-moz-background-clip": {
        comment: "deprecated syntax in old Firefox, https://developer.mozilla.org/en/docs/Web/CSS/background-clip",
        syntax: "padding | border"
      },
      "-moz-border-radius-bottomleft": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/border-bottom-left-radius",
        syntax: "<'border-bottom-left-radius'>"
      },
      "-moz-border-radius-bottomright": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/border-bottom-right-radius",
        syntax: "<'border-bottom-right-radius'>"
      },
      "-moz-border-radius-topleft": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/border-top-left-radius",
        syntax: "<'border-top-left-radius'>"
      },
      "-moz-border-radius-topright": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/border-bottom-right-radius",
        syntax: "<'border-bottom-right-radius'>"
      },
      "-moz-control-character-visibility": {
        comment: "firefox specific keywords, https://bugzilla.mozilla.org/show_bug.cgi?id=947588",
        syntax: "visible | hidden"
      },
      "-moz-osx-font-smoothing": {
        comment: "misssed old syntax https://developer.mozilla.org/en-US/docs/Web/CSS/font-smooth",
        syntax: "auto | grayscale"
      },
      "-moz-user-select": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/user-select",
        syntax: "none | text | all | -moz-none"
      },
      "-ms-flex-align": {
        comment: "misssed old syntax implemented in IE, https://www.w3.org/TR/2012/WD-css3-flexbox-20120322/#flex-align",
        syntax: "start | end | center | baseline | stretch"
      },
      "-ms-flex-item-align": {
        comment: "misssed old syntax implemented in IE, https://www.w3.org/TR/2012/WD-css3-flexbox-20120322/#flex-align",
        syntax: "auto | start | end | center | baseline | stretch"
      },
      "-ms-flex-line-pack": {
        comment: "misssed old syntax implemented in IE, https://www.w3.org/TR/2012/WD-css3-flexbox-20120322/#flex-line-pack",
        syntax: "start | end | center | justify | distribute | stretch"
      },
      "-ms-flex-negative": {
        comment: "misssed old syntax implemented in IE; TODO: find references for comfirmation",
        syntax: "<'flex-shrink'>"
      },
      "-ms-flex-pack": {
        comment: "misssed old syntax implemented in IE, https://www.w3.org/TR/2012/WD-css3-flexbox-20120322/#flex-pack",
        syntax: "start | end | center | justify | distribute"
      },
      "-ms-flex-order": {
        comment: "misssed old syntax implemented in IE; https://msdn.microsoft.com/en-us/library/jj127303(v=vs.85).aspx",
        syntax: "<integer>"
      },
      "-ms-flex-positive": {
        comment: "misssed old syntax implemented in IE; TODO: find references for comfirmation",
        syntax: "<'flex-grow'>"
      },
      "-ms-flex-preferred-size": {
        comment: "misssed old syntax implemented in IE; TODO: find references for comfirmation",
        syntax: "<'flex-basis'>"
      },
      "-ms-interpolation-mode": {
        comment: "https://msdn.microsoft.com/en-us/library/ff521095(v=vs.85).aspx",
        syntax: "nearest-neighbor | bicubic"
      },
      "-ms-grid-column-align": {
        comment: "add this property first since it uses as fallback for flexbox, https://msdn.microsoft.com/en-us/library/windows/apps/hh466338.aspx",
        syntax: "start | end | center | stretch"
      },
      "-ms-grid-row-align": {
        comment: "add this property first since it uses as fallback for flexbox, https://msdn.microsoft.com/en-us/library/windows/apps/hh466348.aspx",
        syntax: "start | end | center | stretch"
      },
      "-ms-hyphenate-limit-last": {
        comment: "misssed old syntax implemented in IE; https://www.w3.org/TR/css-text-4/#hyphenate-line-limits",
        syntax: "none | always | column | page | spread"
      },
      "-webkit-appearance": {
        comment: "webkit specific keywords",
        references: [
          "http://css-infos.net/property/-webkit-appearance"
        ],
        syntax: "none | button | button-bevel | caps-lock-indicator | caret | checkbox | default-button | inner-spin-button | listbox | listitem | media-controls-background | media-controls-fullscreen-background | media-current-time-display | media-enter-fullscreen-button | media-exit-fullscreen-button | media-fullscreen-button | media-mute-button | media-overlay-play-button | media-play-button | media-seek-back-button | media-seek-forward-button | media-slider | media-sliderthumb | media-time-remaining-display | media-toggle-closed-captions-button | media-volume-slider | media-volume-slider-container | media-volume-sliderthumb | menulist | menulist-button | menulist-text | menulist-textfield | meter | progress-bar | progress-bar-value | push-button | radio | scrollbarbutton-down | scrollbarbutton-left | scrollbarbutton-right | scrollbarbutton-up | scrollbargripper-horizontal | scrollbargripper-vertical | scrollbarthumb-horizontal | scrollbarthumb-vertical | scrollbartrack-horizontal | scrollbartrack-vertical | searchfield | searchfield-cancel-button | searchfield-decoration | searchfield-results-button | searchfield-results-decoration | slider-horizontal | slider-vertical | sliderthumb-horizontal | sliderthumb-vertical | square-button | textarea | textfield | -apple-pay-button"
      },
      "-webkit-background-clip": {
        comment: "https://developer.mozilla.org/en/docs/Web/CSS/background-clip",
        syntax: "[ <visual-box> | border | padding | content | text ]#"
      },
      "-webkit-column-break-after": {
        comment: "added, http://help.dottoro.com/lcrthhhv.php",
        syntax: "always | auto | avoid"
      },
      "-webkit-column-break-before": {
        comment: "added, http://help.dottoro.com/lcxquvkf.php",
        syntax: "always | auto | avoid"
      },
      "-webkit-column-break-inside": {
        comment: "added, http://help.dottoro.com/lclhnthl.php",
        syntax: "always | auto | avoid"
      },
      "-webkit-font-smoothing": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/font-smooth",
        syntax: "auto | none | antialiased | subpixel-antialiased"
      },
      "-webkit-mask-box-image": {
        comment: "missed; https://developer.mozilla.org/en-US/docs/Web/CSS/-webkit-mask-box-image",
        syntax: "[ <url> | <gradient> | none ] [ <length-percentage>{4} <-webkit-mask-box-repeat>{2} ]?"
      },
      "-webkit-print-color-adjust": {
        comment: "missed",
        references: [
          "https://developer.mozilla.org/en/docs/Web/CSS/-webkit-print-color-adjust"
        ],
        syntax: "economy | exact"
      },
      "-webkit-text-security": {
        comment: "missed; http://help.dottoro.com/lcbkewgt.php",
        syntax: "none | circle | disc | square"
      },
      "-webkit-user-drag": {
        comment: "missed; http://help.dottoro.com/lcbixvwm.php",
        syntax: "none | element | auto"
      },
      "-webkit-user-select": {
        comment: "auto is supported by old webkit, https://developer.mozilla.org/en-US/docs/Web/CSS/user-select",
        syntax: "auto | none | text | all"
      },
      "alignment-baseline": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#AlignmentBaselineProperty"
        ],
        syntax: "auto | baseline | before-edge | text-before-edge | middle | central | after-edge | text-after-edge | ideographic | alphabetic | hanging | mathematical"
      },
      "baseline-shift": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#BaselineShiftProperty"
        ],
        syntax: "baseline | sub | super | <svg-length>"
      },
      behavior: {
        comment: "added old IE property https://msdn.microsoft.com/en-us/library/ms530723(v=vs.85).aspx",
        syntax: "<url>+"
      },
      "container-type": {
        comment: "https://www.w3.org/TR/css-contain-3/#propdef-container-type",
        syntax: "normal || [ size | inline-size ]"
      },
      cue: {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<'cue-before'> <'cue-after'>?"
      },
      "cue-after": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<url> <decibel>? | none"
      },
      "cue-before": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<url> <decibel>? | none"
      },
      cursor: {
        comment: "added legacy keywords: hand, -webkit-grab. -webkit-grabbing, -webkit-zoom-in, -webkit-zoom-out, -moz-grab, -moz-grabbing, -moz-zoom-in, -moz-zoom-out",
        references: [
          "https://www.sitepoint.com/css3-cursor-styles/"
        ],
        syntax: "[ [ <url> [ <x> <y> ]? , ]* [ auto | default | none | context-menu | help | pointer | progress | wait | cell | crosshair | text | vertical-text | alias | copy | move | no-drop | not-allowed | e-resize | n-resize | ne-resize | nw-resize | s-resize | se-resize | sw-resize | w-resize | ew-resize | ns-resize | nesw-resize | nwse-resize | col-resize | row-resize | all-scroll | zoom-in | zoom-out | grab | grabbing | hand | -webkit-grab | -webkit-grabbing | -webkit-zoom-in | -webkit-zoom-out | -moz-grab | -moz-grabbing | -moz-zoom-in | -moz-zoom-out ] ]"
      },
      display: {
        comment: "extended with -ms-flexbox",
        syntax: "| <-non-standard-display>"
      },
      position: {
        comment: "extended with -webkit-sticky",
        syntax: "| -webkit-sticky"
      },
      "dominant-baseline": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#DominantBaselineProperty"
        ],
        syntax: "auto | use-script | no-change | reset-size | ideographic | alphabetic | hanging | mathematical | central | middle | text-after-edge | text-before-edge"
      },
      "image-rendering": {
        comment: "extended with <-non-standard-image-rendering>, added SVG keywords optimizeSpeed and optimizeQuality",
        references: [
          "https://developer.mozilla.org/en/docs/Web/CSS/image-rendering",
          "https://www.w3.org/TR/SVG/painting.html#ImageRenderingProperty"
        ],
        syntax: "| optimizeSpeed | optimizeQuality | <-non-standard-image-rendering>"
      },
      "fill-opacity": {
        comment: "added SVG property",
        references: [
          "https://developer.mozilla.org/en-US/docs/Web/CSS/fill-opacity",
          "https://www.w3.org/TR/SVG/painting.html#FillProperty"
        ],
        syntax: "<number-zero-one> | <percentage>"
      },
      filter: {
        comment: "extend with IE legacy syntaxes",
        syntax: "| <-ms-filter-function-list>"
      },
      font: {
        comment: "align with font-4, fix <'font-family'>#, add non standard fonts",
        references: [
          "https://drafts.csswg.org/css-fonts-4/#font-prop",
          "https://github.com/w3c/csswg-drafts/pull/10832",
          "https://webkit.org/blog/3709/using-the-system-font-in-web-content/"
        ],
        syntax: "[ [ <'font-style'> || <font-variant-css2> || <'font-weight'> || <font-width-css3> ]? <'font-size'> [ / <'line-height'> ]? <'font-family'># ] | <system-family-name> | <-non-standard-font>"
      },
      "glyph-orientation-horizontal": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#GlyphOrientationHorizontalProperty"
        ],
        syntax: "<angle>"
      },
      "glyph-orientation-vertical": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#GlyphOrientationVerticalProperty"
        ],
        syntax: "<angle>"
      },
      kerning: {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/text.html#KerningProperty"
        ],
        syntax: "auto | <svg-length>"
      },
      "letter-spacing": {
        comment: "fix syntax <length> -> <length-percentage>",
        references: [
          "https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/letter-spacing"
        ],
        syntax: "normal | <length-percentage>"
      },
      "max-width": {
        comment: "extend by non-standard size keywords https://developer.mozilla.org/en-US/docs/Web/CSS/width",
        syntax: "| stretch | <-non-standard-size>"
      },
      "max-height": {
        comment: "extend by non-standard size keywords https://developer.mozilla.org/en-US/docs/Web/CSS/width",
        syntax: "| stretch | <-non-standard-size>"
      },
      width: {
        references: [
          "https://developer.mozilla.org/en-US/docs/Web/CSS/width",
          "https://github.com/csstree/stylelint-validator/issues/29"
        ],
        syntax: "| stretch | <-non-standard-size>"
      },
      height: {
        syntax: "| stretch | <-non-standard-size>"
      },
      "min-width": {
        comment: "extend by non-standard width keywords https://developer.mozilla.org/en-US/docs/Web/CSS/width",
        syntax: "| stretch | <-non-standard-size>"
      },
      "min-height": {
        syntax: "| stretch | <-non-standard-size>"
      },
      overflow: {
        comment: "extend by vendor keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow",
        syntax: "| <-non-standard-overflow>"
      },
      "overflow-x": {
        comment: "extend by vendor keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-x",
        syntax: "| <-non-standard-overflow>"
      },
      "overflow-y": {
        comment: "extend by vendor keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-y",
        syntax: "| <-non-standard-overflow>"
      },
      "overflow-block": {
        comment: "extend by vendor keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-y",
        syntax: "| <-non-standard-overflow>"
      },
      "overflow-inline": {
        comment: "extend by vendor keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow-x",
        syntax: "| <-non-standard-overflow>"
      },
      pause: {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<'pause-before'> <'pause-after'>?"
      },
      "pause-after": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<time> | none | x-weak | weak | medium | strong | x-strong"
      },
      "pause-before": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<time> | none | x-weak | weak | medium | strong | x-strong"
      },
      "position-try-options": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/position-try-fallbacks",
        syntax: "<'position-try-fallbacks'>"
      },
      rest: {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<'rest-before'> <'rest-after'>?"
      },
      "rest-after": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<time> | none | x-weak | weak | medium | strong | x-strong"
      },
      "rest-before": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<time> | none | x-weak | weak | medium | strong | x-strong"
      },
      speak: {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "auto | never | always"
      },
      "stroke-dasharray": {
        comment: "added SVG property; a list of comma and/or white space separated <length>s and <percentage>s",
        references: [
          "https://www.w3.org/TR/SVG/painting.html#StrokeProperties"
        ],
        syntax: "none | [ <svg-length>+ ]#"
      },
      "stroke-dashoffset": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/painting.html#StrokeProperties"
        ],
        syntax: "<svg-length>"
      },
      "stroke-linejoin": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/painting.html#StrokeProperties"
        ],
        syntax: "miter | round | bevel"
      },
      "stroke-miterlimit": {
        comment: "added SVG property (<miterlimit> = <number-one-or-greater>) ",
        references: [
          "https://www.w3.org/TR/SVG/painting.html#StrokeProperties"
        ],
        syntax: "<number-one-or-greater>"
      },
      "stroke-width": {
        comment: "added SVG property",
        references: [
          "https://www.w3.org/TR/SVG/painting.html#StrokeProperties"
        ],
        syntax: "<svg-length>"
      },
      "unicode-bidi": {
        comment: "added prefixed keywords https://developer.mozilla.org/en-US/docs/Web/CSS/unicode-bidi",
        syntax: "| -moz-isolate | -moz-isolate-override | -moz-plaintext | -webkit-isolate | -webkit-isolate-override | -webkit-plaintext"
      },
      "voice-balance": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<number> | left | center | right | leftwards | rightwards"
      },
      "voice-duration": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "auto | <time>"
      },
      "voice-family": {
        comment: "<name> -> <family-name>, https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "[ [ <family-name> | <generic-voice> ] , ]* [ <family-name> | <generic-voice> ] | preserve"
      },
      "voice-pitch": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<frequency> && absolute | [ [ x-low | low | medium | high | x-high ] || [ <frequency> | <semitones> | <percentage> ] ]"
      },
      "voice-range": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "<frequency> && absolute | [ [ x-low | low | medium | high | x-high ] || [ <frequency> | <semitones> | <percentage> ] ]"
      },
      "voice-rate": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "[ normal | x-slow | slow | medium | fast | x-fast ] || <percentage>"
      },
      "voice-stress": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "normal | strong | moderate | none | reduced"
      },
      "voice-volume": {
        comment: "https://www.w3.org/TR/css3-speech/#property-index",
        syntax: "silent | [ [ x-soft | soft | medium | loud | x-loud ] || <decibel> ]"
      },
      "writing-mode": {
        comment: "extend with SVG keywords",
        syntax: "| <svg-writing-mode>"
      },
      "white-space-trim": {
        syntax: "none | discard-before || discard-after || discard-inner",
        comment: "missed, https://www.w3.org/TR/css-text-4/#white-space-trim"
      }
    },
    types: {
      "-legacy-gradient": {
        comment: "added collection of legacy gradient syntaxes",
        syntax: "<-webkit-gradient()> | <-legacy-linear-gradient> | <-legacy-repeating-linear-gradient> | <-legacy-radial-gradient> | <-legacy-repeating-radial-gradient>"
      },
      "-legacy-linear-gradient": {
        comment: "like standard syntax but w/o `to` keyword https://developer.mozilla.org/en-US/docs/Web/CSS/linear-gradient",
        syntax: "-moz-linear-gradient( <-legacy-linear-gradient-arguments> ) | -webkit-linear-gradient( <-legacy-linear-gradient-arguments> ) | -o-linear-gradient( <-legacy-linear-gradient-arguments> )"
      },
      "-legacy-repeating-linear-gradient": {
        comment: "like standard syntax but w/o `to` keyword https://developer.mozilla.org/en-US/docs/Web/CSS/linear-gradient",
        syntax: "-moz-repeating-linear-gradient( <-legacy-linear-gradient-arguments> ) | -webkit-repeating-linear-gradient( <-legacy-linear-gradient-arguments> ) | -o-repeating-linear-gradient( <-legacy-linear-gradient-arguments> )"
      },
      "-legacy-linear-gradient-arguments": {
        comment: "like standard syntax but w/o `to` keyword https://developer.mozilla.org/en-US/docs/Web/CSS/linear-gradient",
        syntax: "[ <angle> | <side-or-corner> ]? , <color-stop-list>"
      },
      "-legacy-radial-gradient": {
        comment: "deprecated syntax that implemented by some browsers https://www.w3.org/TR/2011/WD-css3-images-20110908/#radial-gradients",
        syntax: "-moz-radial-gradient( <-legacy-radial-gradient-arguments> ) | -webkit-radial-gradient( <-legacy-radial-gradient-arguments> ) | -o-radial-gradient( <-legacy-radial-gradient-arguments> )"
      },
      "-legacy-repeating-radial-gradient": {
        comment: "deprecated syntax that implemented by some browsers https://www.w3.org/TR/2011/WD-css3-images-20110908/#radial-gradients",
        syntax: "-moz-repeating-radial-gradient( <-legacy-radial-gradient-arguments> ) | -webkit-repeating-radial-gradient( <-legacy-radial-gradient-arguments> ) | -o-repeating-radial-gradient( <-legacy-radial-gradient-arguments> )"
      },
      "-legacy-radial-gradient-arguments": {
        comment: "deprecated syntax that implemented by some browsers https://www.w3.org/TR/2011/WD-css3-images-20110908/#radial-gradients",
        syntax: "[ <position> , ]? [ [ [ <-legacy-radial-gradient-shape> || <-legacy-radial-gradient-size> ] | [ <length> | <percentage> ]{2} ] , ]? <color-stop-list>"
      },
      "-legacy-radial-gradient-size": {
        comment: "before a standard it contains 2 extra keywords (`contain` and `cover`) https://www.w3.org/TR/2011/WD-css3-images-20110908/#ltsize",
        syntax: "closest-side | closest-corner | farthest-side | farthest-corner | contain | cover"
      },
      "-legacy-radial-gradient-shape": {
        comment: "define to double sure it doesn't extends in future https://www.w3.org/TR/2011/WD-css3-images-20110908/#ltshape",
        syntax: "circle | ellipse"
      },
      "-non-standard-font": {
        comment: "non standard fonts",
        references: [
          "https://webkit.org/blog/3709/using-the-system-font-in-web-content/"
        ],
        syntax: "-apple-system-body | -apple-system-headline | -apple-system-subheadline | -apple-system-caption1 | -apple-system-caption2 | -apple-system-footnote | -apple-system-short-body | -apple-system-short-headline | -apple-system-short-subheadline | -apple-system-short-caption1 | -apple-system-short-footnote | -apple-system-tall-body"
      },
      "-non-standard-color": {
        comment: "non standard colors",
        references: [
          "http://cssdot.ru/%D0%A1%D0%BF%D1%80%D0%B0%D0%B2%D0%BE%D1%87%D0%BD%D0%B8%D0%BA_CSS/color-i305.html",
          "https://developer.mozilla.org/en-US/docs/Web/CSS/color_value#Mozilla_Color_Preference_Extensions"
        ],
        syntax: "-moz-ButtonDefault | -moz-ButtonHoverFace | -moz-ButtonHoverText | -moz-CellHighlight | -moz-CellHighlightText | -moz-Combobox | -moz-ComboboxText | -moz-Dialog | -moz-DialogText | -moz-dragtargetzone | -moz-EvenTreeRow | -moz-Field | -moz-FieldText | -moz-html-CellHighlight | -moz-html-CellHighlightText | -moz-mac-accentdarkestshadow | -moz-mac-accentdarkshadow | -moz-mac-accentface | -moz-mac-accentlightesthighlight | -moz-mac-accentlightshadow | -moz-mac-accentregularhighlight | -moz-mac-accentregularshadow | -moz-mac-chrome-active | -moz-mac-chrome-inactive | -moz-mac-focusring | -moz-mac-menuselect | -moz-mac-menushadow | -moz-mac-menutextselect | -moz-MenuHover | -moz-MenuHoverText | -moz-MenuBarText | -moz-MenuBarHoverText | -moz-nativehyperlinktext | -moz-OddTreeRow | -moz-win-communicationstext | -moz-win-mediatext | -moz-activehyperlinktext | -moz-default-background-color | -moz-default-color | -moz-hyperlinktext | -moz-visitedhyperlinktext | -webkit-activelink | -webkit-focus-ring-color | -webkit-link | -webkit-text"
      },
      "-non-standard-image-rendering": {
        comment: "non-standard keywords http://phrogz.net/tmp/canvas_image_zoom.html",
        syntax: "optimize-contrast | -moz-crisp-edges | -o-crisp-edges | -webkit-optimize-contrast"
      },
      "-non-standard-overflow": {
        comment: "non-standard keywords https://developer.mozilla.org/en-US/docs/Web/CSS/overflow",
        syntax: "overlay | -moz-scrollbars-none | -moz-scrollbars-horizontal | -moz-scrollbars-vertical | -moz-hidden-unscrollable"
      },
      "-non-standard-size": {
        comment: "non-standard keywords https://developer.mozilla.org/en-US/docs/Web/CSS/width",
        syntax: "intrinsic | min-intrinsic | -webkit-fill-available | -webkit-fit-content | -webkit-min-content | -webkit-max-content  | -moz-available | -moz-fit-content | -moz-min-content | -moz-max-content"
      },
      "-webkit-gradient()": {
        comment: "first Apple proposal gradient syntax https://webkit.org/blog/175/introducing-css-gradients/ - TODO: simplify when after match algorithm improvement ( [, point, radius | , point] -> [, radius]? , point )",
        syntax: "-webkit-gradient( <-webkit-gradient-type>, <-webkit-gradient-point> [, <-webkit-gradient-point> | , <-webkit-gradient-radius>, <-webkit-gradient-point> ] [, <-webkit-gradient-radius>]? [, <-webkit-gradient-color-stop>]* )"
      },
      "-webkit-gradient-color-stop": {
        comment: "first Apple proposal gradient syntax https://webkit.org/blog/175/introducing-css-gradients/",
        syntax: "from( <color> ) | color-stop( [ <number-zero-one> | <percentage> ] , <color> ) | to( <color> )"
      },
      "-webkit-gradient-point": {
        comment: "first Apple proposal gradient syntax https://webkit.org/blog/175/introducing-css-gradients/",
        syntax: "[ left | center | right | <length-percentage> ] [ top | center | bottom | <length-percentage> ]"
      },
      "-webkit-gradient-radius": {
        comment: "first Apple proposal gradient syntax https://webkit.org/blog/175/introducing-css-gradients/",
        syntax: "<length> | <percentage>"
      },
      "-webkit-gradient-type": {
        comment: "first Apple proposal gradient syntax https://webkit.org/blog/175/introducing-css-gradients/",
        syntax: "linear | radial"
      },
      "-webkit-mask-box-repeat": {
        comment: "missed; https://developer.mozilla.org/en-US/docs/Web/CSS/-webkit-mask-box-image",
        syntax: "repeat | stretch | round"
      },
      "-ms-filter-function-list": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/-ms-filter",
        syntax: "<-ms-filter-function>+"
      },
      "-ms-filter-function": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/-ms-filter",
        syntax: "<-ms-filter-function-progid> | <-ms-filter-function-legacy>"
      },
      "-ms-filter-function-progid": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/-ms-filter",
        syntax: "'progid:' [ <ident-token> '.' ]* [ <ident-token> | <function-token> <any-value>? ) ]"
      },
      "-ms-filter-function-legacy": {
        comment: "https://developer.mozilla.org/en-US/docs/Web/CSS/-ms-filter",
        syntax: "<ident-token> | <function-token> <any-value>? )"
      },
      age: {
        comment: "https://www.w3.org/TR/css3-speech/#voice-family",
        syntax: "child | young | old"
      },
      "attr-name": {
        syntax: "<wq-name>"
      },
      "attr-fallback": {
        syntax: "<any-value>"
      },
      autospace: {
        syntax: "no-autospace | [ ideograph-alpha || ideograph-numeric || punctuation ] || [ insert | replace ]"
      },
      bottom: {
        comment: "missed; not sure we should add it, but no others except `shape` is using it so it's ok for now; https://drafts.fxtf.org/css-masking-1/#funcdef-clip-rect",
        syntax: "<length> | auto"
      },
      "content-list": {
        comment: "added attr(), see https://github.com/csstree/csstree/issues/201",
        syntax: "[ <string> | contents | <image> | <counter> | <quote> | <target> | <leader()> | <attr()> ]+"
      },
      "container-condition": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#container-rule",
        syntax: "not <query-in-parens> | <query-in-parens> [ [ and <query-in-parens> ]* | [ or <query-in-parens> ]* ]"
      },
      "coord-box": {
        syntax: "content-box | padding-box | border-box | fill-box | stroke-box | view-box"
      },
      "cubic-bezier-easing-function": {
        comment: "missed, https://drafts.csswg.org/css-easing-1/#cubic-bezier-easing-function",
        syntax: "ease | ease-in | ease-out | ease-in-out | cubic-bezier( <number [0,1]> , <number> , <number [0,1]> , <number> )"
      },
      "element()": {
        comment: "https://drafts.csswg.org/css-gcpm/#element-syntax & https://drafts.csswg.org/css-images-4/#element-notation",
        syntax: "element( <custom-ident> , [ first | start | last | first-except ]? ) | element( <id-selector> )"
      },
      "generic-voice": {
        comment: "https://www.w3.org/TR/css3-speech/#voice-family",
        syntax: "[ <age>? <gender> <integer>? ]"
      },
      gender: {
        comment: "https://www.w3.org/TR/css3-speech/#voice-family",
        syntax: "male | female | neutral"
      },
      "general-enclosed": {
        comment: "remove ident-token, optional any-value, brackets (see https://drafts.csswg.org/mediaqueries-5/#typedef-general-enclosed)",
        syntax: "[ <function-token> <any-value>? ) ] | [ ( <any-value>? ) ]"
      },
      "generic-family": {
        comment: "new definition on font-4, https://drafts.csswg.org/css-fonts-4/#typedef-generic-family",
        syntax: "<generic-script-specific>| <generic-complete> | <generic-incomplete> | <-non-standard-generic-family>"
      },
      "generic-script-specific": {
        syntax: "generic(kai) | generic(fangsong) | generic(nastaliq)"
      },
      "-non-standard-generic-family": {
        syntax: "-apple-system | BlinkMacSystemFont",
        references: [
          "https://css-tricks.com/snippets/css/system-font-stack/",
          "https://webkit.org/blog/3709/using-the-system-font-in-web-content/"
        ]
      },
      gradient: {
        comment: "added legacy syntaxes support",
        syntax: "| <-legacy-gradient>"
      },
      "intrinsic-size-keyword": {
        comment: "Missing from mdn-data. 4.3. Intrinsic Size Keywords https://www.w3.org/TR/css-sizing-4/#intrinsic-size-keywords",
        syntax: "min-content | max-content | fit-content"
      },
      left: {
        comment: "missed; not sure we should add it, but no others except `shape` is using it so it's ok for now; https://drafts.fxtf.org/css-masking-1/#funcdef-clip-rect",
        syntax: "<length> | auto"
      },
      color: {
        comment: "css-color-5, added non standard color names",
        syntax: "<color-base> | currentColor | <system-color> | <device-cmyk()>  | <light-dark()> | <-non-standard-color>"
      },
      "device-cmyk()": {
        syntax: "<legacy-device-cmyk-syntax> | <modern-device-cmyk-syntax>"
      },
      "legacy-device-cmyk-syntax": {
        syntax: "device-cmyk( <number>#{4} )"
      },
      "modern-device-cmyk-syntax": {
        syntax: "device-cmyk( <cmyk-component>{4} [ / [ <alpha-value> | none ] ]? )"
      },
      "cmyk-component": {
        syntax: "<number> | <percentage> | none"
      },
      "color-mix()": {
        syntax: "color-mix( <color-interpolation-method> , [ <color> && <percentage [0,100]>? ]#{2} )"
      },
      "color-space": {
        syntax: "<rectangular-color-space> | <polar-color-space> | <custom-color-space>"
      },
      paint: {
        comment: "used by SVG https://www.w3.org/TR/SVG/painting.html#SpecifyingPaint",
        syntax: "none | <color> | <url> [ none | <color> ]? | context-fill | context-stroke"
      },
      right: {
        comment: "missed; not sure we should add it, but no others except `shape` is using it so it's ok for now; https://drafts.fxtf.org/css-masking-1/#funcdef-clip-rect",
        syntax: "<length> | auto"
      },
      shape: {
        comment: "missed spaces in function body and add backwards compatible syntax",
        syntax: "rect( <top>, <right>, <bottom>, <left> ) | rect( <top> <right> <bottom> <left> )"
      },
      "scope-start": {
        syntax: "<forgiving-selector-list>"
      },
      "scope-end": {
        syntax: "<forgiving-selector-list>"
      },
      "forgiving-selector-list": {
        syntax: "<complex-real-selector-list>"
      },
      "forgiving-relative-selector-list": {
        syntax: "<relative-real-selector-list>"
      },
      "complex-real-selector-list": {
        syntax: "<complex-real-selector>#"
      },
      "simple-selector-list": {
        syntax: "<simple-selector>#"
      },
      "relative-real-selector-list": {
        syntax: "<relative-real-selector>#"
      },
      "complex-selector": {
        syntax: "<complex-selector-unit> [ <combinator>? <complex-selector-unit> ]*"
      },
      "complex-selector-unit": {
        syntax: "[ <compound-selector>? <pseudo-compound-selector>* ]!"
      },
      "complex-real-selector": {
        syntax: "<compound-selector> [ <combinator>? <compound-selector> ]*"
      },
      "relative-real-selector": {
        syntax: "<combinator>? <complex-real-selector>"
      },
      "compound-selector": {
        syntax: "[ <type-selector>? <subclass-selector>* ]!"
      },
      "pseudo-compound-selector": {
        syntax: " <pseudo-element-selector> <pseudo-class-selector>*"
      },
      "simple-selector": {
        syntax: "<type-selector> | <subclass-selector>"
      },
      combinator: {
        syntax: "'>' | '+' | '~' | [ '|' '|' ]"
      },
      "pseudo-element-selector": {
        syntax: "':' <pseudo-class-selector> | <legacy-pseudo-element-selector>"
      },
      "legacy-pseudo-element-selector": {
        syntax: " ':' [before | after | first-line | first-letter]"
      },
      "svg-length": {
        comment: "All coordinates and lengths in SVG can be specified with or without a unit identifier",
        references: [
          "https://www.w3.org/TR/SVG11/coords.html#Units"
        ],
        syntax: "<percentage> | <length> | <number>"
      },
      "svg-writing-mode": {
        comment: "SVG specific keywords (deprecated for CSS)",
        references: [
          "https://developer.mozilla.org/en/docs/Web/CSS/writing-mode",
          "https://www.w3.org/TR/SVG/text.html#WritingModeProperty"
        ],
        syntax: "lr-tb | rl-tb | tb-rl | lr | rl | tb"
      },
      top: {
        comment: "missed; not sure we should add it, but no others except `shape` is using it so it's ok for now; https://drafts.fxtf.org/css-masking-1/#funcdef-clip-rect",
        syntax: "<length> | auto"
      },
      x: {
        comment: "missed; not sure we should add it, but no others except `cursor` is using it so it's ok for now; https://drafts.csswg.org/css-ui-3/#cursor",
        syntax: "<number>"
      },
      y: {
        comment: "missed; not sure we should add it, but no others except `cursor` is using so it's ok for now; https://drafts.csswg.org/css-ui-3/#cursor",
        syntax: "<number>"
      },
      declaration: {
        comment: "missed, restored by https://drafts.csswg.org/css-syntax",
        syntax: "<ident-token> : <declaration-value>? [ '!' important ]?"
      },
      "declaration-list": {
        comment: "missed, restored by https://drafts.csswg.org/css-syntax",
        syntax: "[ <declaration>? ';' ]* <declaration>?"
      },
      url: {
        comment: "https://drafts.csswg.org/css-values-4/#urls",
        syntax: "url( <string> <url-modifier>* ) | <url-token>"
      },
      "url-modifier": {
        comment: "https://drafts.csswg.org/css-values-4/#typedef-url-modifier",
        syntax: "<ident> | <function-token> <any-value> )"
      },
      "number-zero-one": {
        syntax: "<number [0,1]>"
      },
      "number-one-or-greater": {
        syntax: "<number [1,∞]>"
      },
      "color()": {
        syntax: "color( <colorspace-params> [ / [ <alpha-value> | none ] ]? )"
      },
      "colorspace-params": {
        syntax: "[ <predefined-rgb-params> | <xyz-params>]"
      },
      "xyz-params": {
        syntax: "<xyz-space> [ <number> | <percentage> | none ]{3}"
      },
      "xyz-space": {
        syntax: "xyz | xyz-d50 | xyz-d65"
      },
      "query-in-parens": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#container-rule",
        syntax: "( <container-condition> ) | ( <size-feature> ) | style( <style-query> ) | <general-enclosed>"
      },
      "size-feature": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#typedef-size-feature",
        syntax: "<mf-plain> | <mf-boolean> | <mf-range>"
      },
      "style-query": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#container-rule",
        syntax: "<style-condition> | <style-feature>"
      },
      "style-condition": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#container-rule",
        syntax: "not <style-in-parens> | <style-in-parens> [ [ and <style-in-parens> ]* | [ or <style-in-parens> ]* ]"
      },
      "style-in-parens": {
        comment: "missed, https://drafts.csswg.org/css-contain-3/#container-rule",
        syntax: "( <style-condition> ) | ( <style-feature> ) | <general-enclosed>"
      },
      "-non-standard-display": {
        syntax: "-ms-inline-flexbox | -ms-grid | -ms-inline-grid | -webkit-flex | -webkit-inline-flex | -webkit-box | -webkit-inline-box | -moz-inline-stack | -moz-box | -moz-inline-box"
      },
      "inset-area": {
        syntax: "[ [ left | center | right | span-left | span-right | x-start | x-end | span-x-start | span-x-end | x-self-start | x-self-end | span-x-self-start | span-x-self-end | span-all ] || [ top | center | bottom | span-top | span-bottom | y-start | y-end | span-y-start | span-y-end | y-self-start | y-self-end | span-y-self-start | span-y-self-end | span-all ] | [ block-start | center | block-end | span-block-start | span-block-end | span-all ] || [ inline-start | center | inline-end | span-inline-start | span-inline-end | span-all ] | [ self-block-start | self-block-end | span-self-block-start | span-self-block-end | span-all ] || [ self-inline-start | self-inline-end | span-self-inline-start | span-self-inline-end | span-all ] | [ start | center | end | span-start | span-end | span-all ]{1,2} | [ self-start | center | self-end | span-self-start | span-self-end | span-all ]{1,2} ]",
        comment: "initial name for <position-area> before renamed",
        references: [
          "https://www.w3.org/TR/css-anchor-position-1/#inset-area"
        ]
      },
      "position-area": {
        syntax: "[ [ left | center | right | span-left | span-right | x-start | x-end | span-x-start | span-x-end | x-self-start | x-self-end | span-x-self-start | span-x-self-end | span-all ] || [ top | center | bottom | span-top | span-bottom | y-start | y-end | span-y-start | span-y-end | y-self-start | y-self-end | span-y-self-start | span-y-self-end | span-all ] | [ block-start | center | block-end | span-block-start | span-block-end | span-all ] || [ inline-start | center | inline-end | span-inline-start | span-inline-end | span-all ] | [ self-block-start | center | self-block-end | span-self-block-start | span-self-block-end | span-all ] || [ self-inline-start | center | self-inline-end | span-self-inline-start | span-self-inline-end | span-all ] | [ start | center | end | span-start | span-end | span-all ]{1,2} | [ self-start | center | self-end | span-self-start | span-self-end | span-all ]{1,2} ]",
        comment: "replaced <inset-area>",
        references: [
          "https://drafts.csswg.org/css-anchor-position-1/#typedef-position-area"
        ]
      },
      syntax: {
        syntax: "'*' | <syntax-component> [ <syntax-combinator> <syntax-component> ]* | <syntax-string>"
      },
      "syntax-component": {
        syntax: "<syntax-single-component> <syntax-multiplier>? | '<' transform-list '>'"
      },
      "syntax-single-component": {
        syntax: "'<' <syntax-type-name> '>' | <ident>"
      },
      "syntax-type-name": {
        syntax: "angle | color | custom-ident | image | integer | length | length-percentage | number | percentage | resolution | string | time | url | transform-function"
      },
      "syntax-combinator": {
        syntax: "'|'"
      },
      "syntax-multiplier": {
        syntax: "'#' | '+'"
      },
      "syntax-string": {
        syntax: "<string>"
      }
    }
  };
});

// ../imp-pinned/node_modules/css-tree/cjs/data-patch.cjs
var require_data_patch = __commonJS((exports, module) => {
  var patch = require_patch();
  var patch$1 = patch;
  module.exports = patch$1;
});

// ../imp-pinned/node_modules/mdn-data/css/at-rules.json
var require_at_rules = __commonJS((exports, module) => {
  module.exports = {
    "@charset": {
      syntax: '@charset "<charset>";',
      groups: [
        "CSS Syntax"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@charset"
    },
    "@counter-style": {
      syntax: `@counter-style <counter-style-name> {
  [ system: <counter-system>; ] ||
  [ symbols: <counter-symbols>; ] ||
  [ additive-symbols: <additive-symbols>; ] ||
  [ negative: <negative-symbol>; ] ||
  [ prefix: <prefix>; ] ||
  [ suffix: <suffix>; ] ||
  [ range: <range>; ] ||
  [ pad: <padding>; ] ||
  [ speak-as: <speak-as>; ] ||
  [ fallback: <counter-style-name>; ]
}`,
      interfaces: [
        "CSSCounterStyleRule"
      ],
      groups: [
        "CSS Counter Styles"
      ],
      descriptors: {
        "additive-symbols": {
          syntax: "[ <integer [0,∞]> && <symbol> ]#",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/additive-symbols"
        },
        fallback: {
          syntax: "<counter-style-name>",
          media: "all",
          initial: "decimal",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/fallback"
        },
        negative: {
          syntax: "<symbol> <symbol>?",
          media: "all",
          initial: '"-" hyphen-minus',
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/negative"
        },
        pad: {
          syntax: "<integer [0,∞]> && <symbol>",
          media: "all",
          initial: '0 ""',
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/pad"
        },
        prefix: {
          syntax: "<symbol>",
          media: "all",
          initial: '""',
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/prefix"
        },
        range: {
          syntax: "[ [ <integer> | infinite ]{2} ]# | auto",
          media: "all",
          initial: "auto",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/range"
        },
        "speak-as": {
          syntax: "auto | bullets | numbers | words | spell-out | <counter-style-name>",
          media: "all",
          initial: "auto",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/speak-as"
        },
        suffix: {
          syntax: "<symbol>",
          media: "all",
          initial: '". "',
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/suffix"
        },
        symbols: {
          syntax: "<symbol>+",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/symbols"
        },
        system: {
          syntax: "cyclic | numeric | alphabetic | symbolic | additive | [ fixed <integer>? ] | [ extends <counter-style-name> ]",
          media: "all",
          initial: "symbolic",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style/system"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@counter-style"
    },
    "@container": {
      syntax: `@container <container-condition># {
  <block-contents>
}`,
      interfaces: [
        "CSSContainerRule"
      ],
      groups: [
        "CSS Conditional Rules"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@container"
    },
    "@document": {
      syntax: `@document [ <url> | url-prefix(<string>) | domain(<string>) | media-document(<string>) | regexp(<string>) ]# {
  <group-rule-body>
}`,
      interfaces: [
        "CSSDocumentRule"
      ],
      groups: [
        "CSS Conditional Rules"
      ],
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@document"
    },
    "@font-face": {
      syntax: `@font-face {
  [ font-family: <family-name>; ] ||
  [ src: <src>; ] ||
  [ unicode-range: <unicode-range>; ] ||
  [ font-variant: <font-variant>; ] ||
  [ font-feature-settings: <font-feature-settings>; ] ||
  [ font-variation-settings: <font-variation-settings>; ] ||
  [ font-stretch: <font-stretch>; ] ||
  [ font-weight: <font-weight>; ] ||
  [ font-style: <font-style>; ] ||
  [ size-adjust: <size-adjust>; ] ||
  [ ascent-override: <ascent-override>; ] ||
  [ descent-override: <descent-override>; ] ||
  [ line-gap-override: <line-gap-override>; ]
}`,
      interfaces: [
        "CSSFontFaceRule"
      ],
      groups: [
        "CSS Fonts"
      ],
      descriptors: {
        "ascent-override": {
          syntax: "normal | <percentage>",
          media: "all",
          initial: "normal",
          percentages: "asSpecified",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/ascent-override"
        },
        "descent-override": {
          syntax: "normal | <percentage>",
          media: "all",
          initial: "normal",
          percentages: "asSpecified",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/descent-override"
        },
        "font-display": {
          syntax: "auto | block | swap | fallback | optional",
          media: "visual",
          percentages: "no",
          initial: "auto",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-display"
        },
        "font-family": {
          syntax: "<family-name>",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-family"
        },
        "font-feature-settings": {
          syntax: "normal | <feature-tag-value>#",
          media: "all",
          initial: "normal",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-feature-settings"
        },
        "font-stretch": {
          syntax: "<font-stretch-absolute>{1,2}",
          media: "all",
          initial: "normal",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "obsolete",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-stretch"
        },
        "font-style": {
          syntax: "normal | italic | oblique <angle>{0,2}",
          media: "all",
          initial: "normal",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-style"
        },
        "font-variation-settings": {
          syntax: "normal | [ <string> <number> ]#",
          media: "all",
          initial: "normal",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-variation-settings"
        },
        "font-weight": {
          syntax: "<font-weight-absolute>{1,2}",
          media: "all",
          initial: "normal",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/font-weight"
        },
        "line-gap-override": {
          syntax: "normal | <percentage>",
          media: "all",
          initial: "normal",
          percentages: "asSpecified",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/line-gap-override"
        },
        "size-adjust": {
          syntax: "<percentage>",
          media: "all",
          initial: "100%",
          percentages: "asSpecified",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/size-adjust"
        },
        src: {
          syntax: "[ <url> [ format( <string># ) ]? | local( <family-name> ) ]#",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/src"
        },
        "unicode-range": {
          syntax: "<unicode-range-token>#",
          media: "all",
          initial: "U+0-10FFFF",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face/unicode-range"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-face"
    },
    "@font-feature-values": {
      syntax: `@font-feature-values <family-name># {
  <feature-value-block-list>
}`,
      interfaces: [
        "CSSFontFeatureValuesRule"
      ],
      groups: [
        "CSS Fonts"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-feature-values"
    },
    "@font-palette-values": {
      syntax: `@font-palette-values <dashed-ident> {
  <declaration-list>
}`,
      interfaces: [
        "CSSFontPaletteValuesRule"
      ],
      groups: [
        "CSS Fonts"
      ],
      descriptors: {
        "base-palette": {
          syntax: "light | dark | <integer [0,∞]>",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-palette-values/base-palette"
        },
        "font-family": {
          syntax: "<family-name>#",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-palette-values/font-family"
        },
        "override-colors": {
          syntax: "[ <integer [0,∞]> <color> ]#",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-palette-values/override-colors"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@font-palette-values"
    },
    "@import": {
      syntax: `@import [ <string> | <url> ]
        [ layer | layer(<layer-name>) ]?
        [ supports( [ <supports-condition> | <declaration> ] ) ]?
        <media-query-list>? ;`,
      interfaces: [
        "CSSImportRule"
      ],
      groups: [
        "CSS Cascading and Inheritance"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@import"
    },
    "@keyframes": {
      syntax: `@keyframes <keyframes-name> {
  <qualified-rule-list>
}`,
      interfaces: [
        "CSSKeyframeRule",
        "CSSKeyframesRule"
      ],
      groups: [
        "CSS Animations"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@keyframes"
    },
    "@layer": {
      syntax: `@layer [ <layer-name># | <layer-name>?  {
  <stylesheet>
} ]`,
      interfaces: [
        "CSSLayerBlockRule",
        "CSSLayerStatementRule"
      ],
      groups: [
        "CSS Cascading and Inheritance"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@layer"
    },
    "@media": {
      syntax: `@media <media-query-list> {
  <group-rule-body>
}`,
      interfaces: [
        "CSSMediaRule"
      ],
      groups: [
        "CSS Conditional Rules",
        "Media Queries"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@media"
    },
    "@namespace": {
      syntax: "@namespace <namespace-prefix>? [ <string> | <url> ];",
      interfaces: [
        "CSSNamespaceRule"
      ],
      groups: [
        "CSS Namespaces"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@namespace"
    },
    "@page": {
      syntax: `@page <page-selector-list> {
  <page-body>
}`,
      interfaces: [
        "CSSPageRule"
      ],
      groups: [
        "CSS Paged Media"
      ],
      descriptors: {
        bleed: {
          syntax: "auto | <length>",
          media: [
            "visual",
            "paged"
          ],
          initial: "auto",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard"
        },
        marks: {
          syntax: "none | [ crop || cross ]",
          media: [
            "visual",
            "paged"
          ],
          initial: "none",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard"
        },
        "page-orientation": {
          syntax: "upright | rotate-left | rotate-right",
          media: [
            "visual",
            "paged"
          ],
          initial: "upright",
          percentages: "no",
          computed: "asSpecified",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@page/page-orientation"
        },
        size: {
          syntax: "<length [0,∞]>{1,2} | auto | [ <page-size> || [ portrait | landscape ] ]",
          media: [
            "visual",
            "paged"
          ],
          initial: "auto",
          percentages: "no",
          computed: "asSpecifiedRelativeToAbsoluteLengths",
          order: "orderOfAppearance",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@page/size"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@page"
    },
    "@position-try": {
      syntax: `@position-try <dashed-ident> {
  <declaration-list>
}`,
      interfaces: [
        "CSSPositionTryRule"
      ],
      groups: [
        "CSS Anchor Positioning"
      ],
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@position-try"
    },
    "@property": {
      syntax: `@property <custom-property-name> {
  <declaration-list>
}`,
      interfaces: [
        "CSSPropertyRule"
      ],
      groups: [
        "CSS Houdini"
      ],
      descriptors: {
        inherits: {
          syntax: "true | false",
          media: "all",
          percentages: "no",
          initial: "auto",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@property/inherits"
        },
        "initial-value": {
          syntax: "<declaration-value>?",
          media: "all",
          initial: "n/a (required)",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@property/initial-value"
        },
        syntax: {
          syntax: "<string>",
          media: "all",
          percentages: "no",
          initial: "n/a (required)",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard",
          mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@property/syntax"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@property"
    },
    "@scope": {
      syntax: `@scope [(<scope-start>)]? [to (<scope-end>)]? {
  <rule-list>
}`,
      interfaces: [
        "CSSScopeRule"
      ],
      groups: [
        "CSS Conditional Rules"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@scope"
    },
    "@starting-style": {
      syntax: `@starting-style {
  <declaration-list> | <group-rule-body>
}`,
      interfaces: [
        "CSSStartingStyleRule"
      ],
      groups: [
        "CSS Transitions"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@starting-style"
    },
    "@supports": {
      syntax: `@supports <supports-condition> {
  <group-rule-body>
}`,
      interfaces: [
        "CSSSupportsRule"
      ],
      groups: [
        "CSS Conditional Rules"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@supports"
    },
    "@view-transition": {
      syntax: `@view-transition {
  <declaration-list>
}`,
      interfaces: [
        "CSSViewTransitionRule"
      ],
      groups: [
        "CSS View Transitions"
      ],
      descriptors: {
        navigation: {
          syntax: "auto | none",
          media: "all",
          initial: "none",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard"
        },
        types: {
          syntax: "none | <custom-ident>+",
          media: "all",
          initial: "none",
          percentages: "no",
          computed: "asSpecified",
          order: "uniqueOrder",
          status: "standard"
        }
      },
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/@view-transition"
    }
  };
});

// ../imp-pinned/node_modules/mdn-data/css/properties.json
var require_properties = __commonJS((exports, module) => {
  module.exports = {
    "--*": {
      syntax: "<declaration-value>",
      media: "all",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Custom Properties for Cascading Variables"
      ],
      initial: "seeProse",
      appliesto: "allElements",
      computed: "asSpecifiedWithVarsSubstituted",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/--*"
    },
    "-ms-accelerator": {
      syntax: "false | true",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "false",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-block-progression": {
      syntax: "tb | rl | bt | lr",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "tb",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-chaining": {
      syntax: "none | chained",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-limit": {
      syntax: "<'-ms-content-zoom-limit-min'> <'-ms-content-zoom-limit-max'>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: [
        "-ms-content-zoom-limit-max",
        "-ms-content-zoom-limit-min"
      ],
      groups: [
        "Microsoft Extensions"
      ],
      initial: [
        "-ms-content-zoom-limit-max",
        "-ms-content-zoom-limit-min"
      ],
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "-ms-content-zoom-limit-max",
        "-ms-content-zoom-limit-min"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-limit-max": {
      syntax: "<percentage>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "maxZoomFactor",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "400%",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-limit-min": {
      syntax: "<percentage>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "minZoomFactor",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "100%",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-snap": {
      syntax: "<'-ms-content-zoom-snap-type'> || <'-ms-content-zoom-snap-points'>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: [
        "-ms-content-zoom-snap-type",
        "-ms-content-zoom-snap-points"
      ],
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "-ms-content-zoom-snap-type",
        "-ms-content-zoom-snap-points"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-snap-points": {
      syntax: "snapInterval( <percentage>, <percentage> ) | snapList( <percentage># )",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "snapInterval(0%, 100%)",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zoom-snap-type": {
      syntax: "none | proximity | mandatory",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-content-zooming": {
      syntax: "none | zoom",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "zoomForTheTopLevelNoneForTheRest",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-filter": {
      syntax: "<string>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: '""',
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-flow-from": {
      syntax: "[ none | <custom-ident> ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "nonReplacedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-flow-into": {
      syntax: "[ none | <custom-ident> ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "iframeElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-grid-columns": {
      syntax: "none | <track-list> | <auto-track-list>",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpcDifferenceLpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "none",
      appliesto: "gridContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-grid-rows": {
      syntax: "none | <track-list> | <auto-track-list>",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpcDifferenceLpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "none",
      appliesto: "gridContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-high-contrast-adjust": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-hyphenate-limit-chars": {
      syntax: "auto | <integer>{1,3}",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-hyphenate-limit-lines": {
      syntax: "no-limit | <integer>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "no-limit",
      appliesto: "blockContainerElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-hyphenate-limit-zone": {
      syntax: "<percentage> | <length>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "referToLineBoxWidth",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "0",
      appliesto: "blockContainerElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-ime-align": {
      syntax: "auto | after",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-overflow-style": {
      syntax: "auto | none | scrollbar | -ms-autohiding-scrollbar",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-chaining": {
      syntax: "chained | none",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "chained",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-limit": {
      syntax: "<'-ms-scroll-limit-x-min'> <'-ms-scroll-limit-y-min'> <'-ms-scroll-limit-x-max'> <'-ms-scroll-limit-y-max'>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: [
        "-ms-scroll-limit-x-min",
        "-ms-scroll-limit-y-min",
        "-ms-scroll-limit-x-max",
        "-ms-scroll-limit-y-max"
      ],
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "-ms-scroll-limit-x-min",
        "-ms-scroll-limit-y-min",
        "-ms-scroll-limit-x-max",
        "-ms-scroll-limit-y-max"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-limit-x-max": {
      syntax: "auto | <length>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-limit-x-min": {
      syntax: "<length>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "0",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-limit-y-max": {
      syntax: "auto | <length>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-limit-y-min": {
      syntax: "<length>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "0",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-rails": {
      syntax: "none | railed",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "railed",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-snap-points-x": {
      syntax: "snapInterval( <length-percentage>, <length-percentage> ) | snapList( <length-percentage># )",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "snapInterval(0px, 100%)",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-snap-points-y": {
      syntax: "snapInterval( <length-percentage>, <length-percentage> ) | snapList( <length-percentage># )",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "snapInterval(0px, 100%)",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-snap-type": {
      syntax: "none | proximity | mandatory",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-snap-x": {
      syntax: "<'-ms-scroll-snap-type'> <'-ms-scroll-snap-points-x'>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: [
        "-ms-scroll-snap-type",
        "-ms-scroll-snap-points-x"
      ],
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "-ms-scroll-snap-type",
        "-ms-scroll-snap-points-x"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-snap-y": {
      syntax: "<'-ms-scroll-snap-type'> <'-ms-scroll-snap-points-y'>",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: [
        "-ms-scroll-snap-type",
        "-ms-scroll-snap-points-y"
      ],
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "-ms-scroll-snap-type",
        "-ms-scroll-snap-points-y"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scroll-translation": {
      syntax: "none | vertical-to-horizontal",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-3dlight-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "dependsOnUserAgent",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-arrow-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "ButtonText",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-base-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "dependsOnUserAgent",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-darkshadow-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "ThreeDDarkShadow",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-face-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "ThreeDFace",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-highlight-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "ThreeDHighlight",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-shadow-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "ThreeDDarkShadow",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-scrollbar-track-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "Scrollbar",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-text-autospace": {
      syntax: "none | ideograph-alpha | ideograph-numeric | ideograph-parenthesis | ideograph-space",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-touch-select": {
      syntax: "grippers | none",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "grippers",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-user-select": {
      syntax: "none | element | text",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "text",
      appliesto: "nonReplacedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-wrap-flow": {
      syntax: "auto | both | start | end | maximum | clear",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "auto",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-wrap-margin": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "0",
      appliesto: "exclusionElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-ms-wrap-through": {
      syntax: "wrap | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Microsoft Extensions"
      ],
      initial: "wrap",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-appearance": {
      syntax: "none | button | button-arrow-down | button-arrow-next | button-arrow-previous | button-arrow-up | button-bevel | button-focus | caret | checkbox | checkbox-container | checkbox-label | checkmenuitem | dualbutton | groupbox | listbox | listitem | menuarrow | menubar | menucheckbox | menuimage | menuitem | menuitemtext | menulist | menulist-button | menulist-text | menulist-textfield | menupopup | menuradio | menuseparator | meterbar | meterchunk | progressbar | progressbar-vertical | progresschunk | progresschunk-vertical | radio | radio-container | radio-label | radiomenuitem | range | range-thumb | resizer | resizerpanel | scale-horizontal | scalethumbend | scalethumb-horizontal | scalethumbstart | scalethumbtick | scalethumb-vertical | scale-vertical | scrollbarbutton-down | scrollbarbutton-left | scrollbarbutton-right | scrollbarbutton-up | scrollbarthumb-horizontal | scrollbarthumb-vertical | scrollbartrack-horizontal | scrollbartrack-vertical | searchfield | separator | sheet | spinner | spinner-downbutton | spinner-textfield | spinner-upbutton | splitter | statusbar | statusbarpanel | tab | tabpanel | tabpanels | tab-scroll-arrow-back | tab-scroll-arrow-forward | textfield | textfield-multiline | toolbar | toolbarbutton | toolbarbutton-dropdown | toolbargripper | toolbox | tooltip | treeheader | treeheadercell | treeheadersortarrow | treeitem | treeline | treetwisty | treetwistyopen | treeview | -moz-mac-unified-toolbar | -moz-win-borderless-glass | -moz-win-browsertabbar-toolbox | -moz-win-communicationstext | -moz-win-communications-toolbox | -moz-win-exclude-glass | -moz-win-glass | -moz-win-mediatext | -moz-win-media-toolbox | -moz-window-button-box | -moz-window-button-box-maximized | -moz-window-button-close | -moz-window-button-maximize | -moz-window-button-minimize | -moz-window-button-restore | -moz-window-frame-bottom | -moz-window-frame-left | -moz-window-frame-right | -moz-window-titlebar | -moz-window-titlebar-maximized",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "noneButOverriddenInUserAgentCSS",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/appearance"
    },
    "-moz-binding": {
      syntax: "<url> | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElementsExceptGeneratedContentOrPseudoElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-border-bottom-colors": {
      syntax: "<color>+ | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-border-left-colors": {
      syntax: "<color>+ | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-border-right-colors": {
      syntax: "<color>+ | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-border-top-colors": {
      syntax: "<color>+ | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-context-properties": {
      syntax: "none | [ fill | fill-opacity | stroke | stroke-opacity ]#",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElementsThatCanReferenceImages",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-float-edge": {
      syntax: "border-box | content-box | margin-box | padding-box",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "content-box",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-moz-float-edge"
    },
    "-moz-force-broken-image-icon": {
      syntax: "0 | 1",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "0",
      appliesto: "images",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-moz-force-broken-image-icon"
    },
    "-moz-orient": {
      syntax: "inline | block | horizontal | vertical",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "inline",
      appliesto: "anyElementEffectOnProgressAndMeter",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-moz-orient"
    },
    "-moz-outline-radius": {
      syntax: "<outline-radius>{1,4} [ / <outline-radius>{1,4} ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "-moz-outline-radius-topleft",
        "-moz-outline-radius-topright",
        "-moz-outline-radius-bottomright",
        "-moz-outline-radius-bottomleft"
      ],
      percentages: [
        "-moz-outline-radius-topleft",
        "-moz-outline-radius-topright",
        "-moz-outline-radius-bottomright",
        "-moz-outline-radius-bottomleft"
      ],
      groups: [
        "Mozilla Extensions"
      ],
      initial: [
        "-moz-outline-radius-topleft",
        "-moz-outline-radius-topright",
        "-moz-outline-radius-bottomright",
        "-moz-outline-radius-bottomleft"
      ],
      appliesto: "allElements",
      computed: [
        "-moz-outline-radius-topleft",
        "-moz-outline-radius-topright",
        "-moz-outline-radius-bottomright",
        "-moz-outline-radius-bottomleft"
      ],
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-outline-radius-bottomleft": {
      syntax: "<outline-radius>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-outline-radius-bottomright": {
      syntax: "<outline-radius>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-outline-radius-topleft": {
      syntax: "<outline-radius>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-outline-radius-topright": {
      syntax: "<outline-radius>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-stack-sizing": {
      syntax: "ignore | stretch-to-fit",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "stretch-to-fit",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-text-blink": {
      syntax: "none | blink",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-user-focus": {
      syntax: "ignore | normal | select-after | select-before | select-menu | select-same | select-all | none",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-moz-user-focus"
    },
    "-moz-user-input": {
      syntax: "auto | none | enabled | disabled",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-moz-user-input"
    },
    "-moz-user-modify": {
      syntax: "read-only | read-write | write-only",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "read-only",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/user-modify"
    },
    "-moz-window-dragging": {
      syntax: "drag | no-drag",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "drag",
      appliesto: "allElementsCreatingNativeWindows",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-moz-window-shadow": {
      syntax: "default | menu | tooltip | sheet | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "default",
      appliesto: "allElementsCreatingNativeWindows",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-webkit-appearance": {
      syntax: "none | button | button-bevel | caret | checkbox | default-button | inner-spin-button | listbox | listitem | media-controls-background | media-controls-fullscreen-background | media-current-time-display | media-enter-fullscreen-button | media-exit-fullscreen-button | media-fullscreen-button | media-mute-button | media-overlay-play-button | media-play-button | media-seek-back-button | media-seek-forward-button | media-slider | media-sliderthumb | media-time-remaining-display | media-toggle-closed-captions-button | media-volume-slider | media-volume-slider-container | media-volume-sliderthumb | menulist | menulist-button | menulist-text | menulist-textfield | meter | progress-bar | progress-bar-value | push-button | radio | searchfield | searchfield-cancel-button | searchfield-decoration | searchfield-results-button | searchfield-results-decoration | slider-horizontal | slider-vertical | sliderthumb-horizontal | sliderthumb-vertical | square-button | textarea | textfield | -apple-pay-button",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "noneButOverriddenInUserAgentCSS",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/appearance"
    },
    "-webkit-border-before": {
      syntax: "<'border-width'> || <'border-style'> || <color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: [
        "-webkit-border-before-width"
      ],
      groups: [
        "WebKit Extensions"
      ],
      initial: [
        "border-width",
        "border-style",
        "color"
      ],
      appliesto: "allElements",
      computed: [
        "border-width",
        "border-style",
        "color"
      ],
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-border-before"
    },
    "-webkit-border-before-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-webkit-border-before-style": {
      syntax: "<'border-style'>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-webkit-border-before-width": {
      syntax: "<'border-width'>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "WebKit Extensions"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-webkit-box-reflect": {
      syntax: "[ above | below | right | left ]? <length>? <image>?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-box-reflect"
    },
    "-webkit-line-clamp": {
      syntax: "none | <integer>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "WebKit Extensions",
        "CSS Overflow"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-line-clamp"
    },
    "-webkit-mask": {
      syntax: "[ <mask-reference> || <position> [ / <bg-size> ]? || <repeat-style> || [ <visual-box> | border | padding | content | text ] || [ <visual-box> | border | padding | content ] ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: [
        "-webkit-mask-image",
        "-webkit-mask-repeat",
        "-webkit-mask-attachment",
        "-webkit-mask-position",
        "-webkit-mask-origin",
        "-webkit-mask-clip"
      ],
      appliesto: "allElements",
      computed: [
        "-webkit-mask-image",
        "-webkit-mask-repeat",
        "-webkit-mask-attachment",
        "-webkit-mask-position",
        "-webkit-mask-origin",
        "-webkit-mask-clip"
      ],
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask"
    },
    "-webkit-mask-attachment": {
      syntax: "<attachment>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "scroll",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard"
    },
    "-webkit-mask-clip": {
      syntax: "[ <coord-box> | no-clip | border | padding | content | text ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "border",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-clip"
    },
    "-webkit-mask-composite": {
      syntax: "<composite-style>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "source-over",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-mask-composite"
    },
    "-webkit-mask-image": {
      syntax: "<mask-reference>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "absoluteURIOrNone",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-image"
    },
    "-webkit-mask-origin": {
      syntax: "[ <coord-box> | border | padding | content ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "padding",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-origin"
    },
    "-webkit-mask-position": {
      syntax: "<position>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "referToSizeOfElement",
      groups: [
        "WebKit Extensions"
      ],
      initial: "0% 0%",
      appliesto: "allElements",
      computed: "absoluteLengthOrPercentage",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-position"
    },
    "-webkit-mask-position-x": {
      syntax: "[ <length-percentage> | left | center | right ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "referToSizeOfElement",
      groups: [
        "WebKit Extensions"
      ],
      initial: "0%",
      appliesto: "allElements",
      computed: "absoluteLengthOrPercentage",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-mask-position-x"
    },
    "-webkit-mask-position-y": {
      syntax: "[ <length-percentage> | top | center | bottom ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "referToSizeOfElement",
      groups: [
        "WebKit Extensions"
      ],
      initial: "0%",
      appliesto: "allElements",
      computed: "absoluteLengthOrPercentage",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-mask-position-y"
    },
    "-webkit-mask-repeat": {
      syntax: "<repeat-style>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "repeat",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-repeat"
    },
    "-webkit-mask-repeat-x": {
      syntax: "repeat | no-repeat | space | round",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "repeat",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-mask-repeat-x"
    },
    "-webkit-mask-repeat-y": {
      syntax: "repeat | no-repeat | space | round",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "repeat",
      appliesto: "allElements",
      computed: "absoluteLengthOrPercentage",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-mask-repeat-y"
    },
    "-webkit-mask-size": {
      syntax: "<bg-size>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "relativeToBackgroundPositioningArea",
      groups: [
        "WebKit Extensions"
      ],
      initial: "auto auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-size"
    },
    "-webkit-overflow-scrolling": {
      syntax: "auto | touch",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "auto",
      appliesto: "scrollingBoxes",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "nonstandard"
    },
    "-webkit-tap-highlight-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "black",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-tap-highlight-color"
    },
    "-webkit-text-fill-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "color",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-text-fill-color"
    },
    "-webkit-text-stroke": {
      syntax: "<length> || <color>",
      media: "visual",
      inherited: true,
      animationType: [
        "-webkit-text-stroke-width",
        "-webkit-text-stroke-color"
      ],
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: [
        "-webkit-text-stroke-width",
        "-webkit-text-stroke-color"
      ],
      appliesto: "allElements",
      computed: [
        "-webkit-text-stroke-width",
        "-webkit-text-stroke-color"
      ],
      order: "canonicalOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-text-stroke"
    },
    "-webkit-text-stroke-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "color",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-text-stroke-color"
    },
    "-webkit-text-stroke-width": {
      syntax: "<length>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "absoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-text-stroke-width"
    },
    "-webkit-touch-callout": {
      syntax: "default | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "default",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/-webkit-touch-callout"
    },
    "-webkit-user-modify": {
      syntax: "read-only | read-write | read-write-plaintext-only",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "read-only",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "-webkit-user-select": {
      syntax: "auto | text | none | all",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "WebKit Extensions"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/user-select"
    },
    "accent-color": {
      syntax: "auto | <color>",
      media: "interactive",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asAutoOrColor",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/accent-color"
    },
    "align-content": {
      syntax: "normal | <baseline-position> | <content-distribution> | <overflow-position>? <content-position>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment",
        "CSS Flexible Box Layout"
      ],
      initial: "normal",
      appliesto: "blockContainersMultiColumnContainersFlexContainersGridContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/align-content"
    },
    "align-items": {
      syntax: "normal | stretch | <baseline-position> | [ <overflow-position>? <self-position> ] | anchor-center",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment",
        "CSS Flexible Box Layout"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/align-items"
    },
    "align-self": {
      syntax: "auto | normal | stretch | <baseline-position> | <overflow-position>? <self-position> | anchor-center",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment",
        "CSS Flexible Box Layout"
      ],
      initial: "auto",
      appliesto: "flexItemsGridItemsAndAbsolutelyPositionedBoxes",
      computed: "autoOnAbsolutelyPositionedElementsValueOfAlignItemsOnParent",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/align-self"
    },
    "align-tracks": {
      syntax: "[ normal | <baseline-position> | <content-distribution> | <overflow-position>? <content-position> ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "normal",
      appliesto: "gridContainersWithMasonryLayoutInTheirBlockAxis",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "alignment-baseline": {
      syntax: "baseline | alphabetic | ideographic | middle | central | mathematical | text-before-edge | text-after-edge",
      media: "none",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "baseline",
      appliesto: "inlineLevelBoxesFlexItemsGridItemsTableCellsAndSVGTextContentElements",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/alignment-baseline"
    },
    all: {
      syntax: "initial | inherit | unset | revert | revert-layer",
      media: "noPracticalMedia",
      inherited: false,
      animationType: "eachOfShorthandPropertiesExceptUnicodeBiDiAndDirection",
      percentages: "no",
      groups: [
        "CSS Cascading and Inheritance"
      ],
      initial: "noPracticalInitialValue",
      appliesto: "allElements",
      computed: "asSpecifiedAppliesToEachProperty",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/all"
    },
    "anchor-name": {
      syntax: "none | <dashed-ident>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "none",
      appliesto: "allElementsThatGenerateAPrincipalBox",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/anchor-name"
    },
    "anchor-scope": {
      syntax: "none | all | <dashed-ident>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental"
    },
    animation: {
      syntax: "<single-animation>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: [
        "animation-name",
        "animation-duration",
        "animation-timing-function",
        "animation-delay",
        "animation-iteration-count",
        "animation-direction",
        "animation-fill-mode",
        "animation-play-state",
        "animation-timeline"
      ],
      appliesto: "allElements",
      computed: [
        "animation-name",
        "animation-duration",
        "animation-timing-function",
        "animation-delay",
        "animation-direction",
        "animation-iteration-count",
        "animation-fill-mode",
        "animation-play-state",
        "animation-timeline"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation"
    },
    "animation-composition": {
      syntax: "<single-animation-composition>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "replace",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-composition"
    },
    "animation-delay": {
      syntax: "<time>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "0s",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-delay"
    },
    "animation-direction": {
      syntax: "<single-animation-direction>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "normal",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-direction"
    },
    "animation-duration": {
      syntax: "[ auto | <time [0s,∞]> ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "0s",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-duration"
    },
    "animation-fill-mode": {
      syntax: "<single-animation-fill-mode>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "none",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-fill-mode"
    },
    "animation-iteration-count": {
      syntax: "<single-animation-iteration-count>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "1",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-iteration-count"
    },
    "animation-name": {
      syntax: "[ none | <keyframes-name> ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "none",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-name"
    },
    "animation-play-state": {
      syntax: "<single-animation-play-state>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "running",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-play-state"
    },
    "animation-range": {
      syntax: "[ <'animation-range-start'> <'animation-range-end'>? ]#",
      media: "visual",
      inherited: false,
      animationType: [
        "animation-range-start",
        "animation-range-end"
      ],
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: [
        "animation-range-start",
        "animation-range-end"
      ],
      appliesto: "allElements",
      computed: [
        "animation-range-start",
        "animation-range-end"
      ],
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-range"
    },
    "animation-range-end": {
      syntax: "[ normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-range-end"
    },
    "animation-range-start": {
      syntax: "[ normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-range-start"
    },
    "animation-timeline": {
      syntax: "<single-animation-timeline>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "listEachItemIdentifierOrNoneAuto",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-timeline"
    },
    "animation-timing-function": {
      syntax: "<easing-function>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "ease",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/animation-timing-function"
    },
    "animation-trigger": {
      syntax: "[ none | [ <dashed-ident> <animation-action>+ ]+ ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/animation-trigger"
    },
    appearance: {
      syntax: "none | auto | <compat-auto> | <compat-special>",
      media: "all",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/appearance"
    },
    "aspect-ratio": {
      syntax: "auto || <ratio>",
      media: "all",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "auto",
      appliesto: "allElementsExceptInlineBoxesAndInternalRubyOrTableBoxes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/aspect-ratio"
    },
    "backdrop-filter": {
      syntax: "none | <filter-value-list>",
      media: "visual",
      inherited: false,
      animationType: "filterList",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "none",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/backdrop-filter"
    },
    "backface-visibility": {
      syntax: "visible | hidden",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "visible",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/backface-visibility"
    },
    background: {
      syntax: "<bg-layer>#? , <final-bg-layer>",
      media: "visual",
      inherited: false,
      animationType: [
        "background-color",
        "background-image",
        "background-clip",
        "background-position",
        "background-size",
        "background-repeat",
        "background-attachment"
      ],
      percentages: [
        "background-position",
        "background-size"
      ],
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "background-image",
        "background-position",
        "background-size",
        "background-repeat",
        "background-origin",
        "background-clip",
        "background-attachment",
        "background-color"
      ],
      appliesto: "allElements",
      computed: [
        "background-image",
        "background-position",
        "background-size",
        "background-repeat",
        "background-origin",
        "background-clip",
        "background-attachment",
        "background-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background"
    },
    "background-attachment": {
      syntax: "<attachment>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "scroll",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-attachment"
    },
    "background-blend-mode": {
      syntax: "<blend-mode>#",
      media: "none",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Compositing and Blending"
      ],
      initial: "normal",
      appliesto: "allElementsSVGContainerGraphicsAndGraphicsReferencingElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-blend-mode"
    },
    "background-clip": {
      syntax: "<bg-clip>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "border-box",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-clip"
    },
    "background-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "transparent",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-color"
    },
    "background-image": {
      syntax: "<bg-image>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecifiedURLsAbsolute",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-image"
    },
    "background-origin": {
      syntax: "<visual-box>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "padding-box",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-origin"
    },
    "background-position": {
      syntax: "<bg-position>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "referToSizeOfBackgroundPositioningAreaMinusBackgroundImageSize",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0% 0%",
      appliesto: "allElements",
      computed: [
        "background-position-x",
        "background-position-y"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-position"
    },
    "background-position-x": {
      syntax: "[ center | [ [ left | right | x-start | x-end ]? <length-percentage>? ]! ]#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "referToWidthOfBackgroundPositioningAreaMinusBackgroundImageWidth",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0%",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfAbsoluteLengthPercentageAndOrigin",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-position-x"
    },
    "background-position-y": {
      syntax: "[ center | [ [ top | bottom | y-start | y-end ]? <length-percentage>? ]! ]#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "referToHeightOfBackgroundPositioningAreaMinusBackgroundImageHeight",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0%",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfAbsoluteLengthPercentageAndOrigin",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-position-y"
    },
    "background-repeat": {
      syntax: "<repeat-style>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "repeat",
      appliesto: "allElements",
      computed: "listEachItemHasTwoKeywordsOnePerDimension",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-repeat"
    },
    "background-size": {
      syntax: "<bg-size>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "relativeToBackgroundPositioningArea",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "auto auto",
      appliesto: "allElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/background-size"
    },
    "baseline-shift": {
      syntax: "<length-percentage> | sub | super | baseline",
      media: "none",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToTheUsedValueOfLineHeight",
      groups: [
        "CSS Inline"
      ],
      initial: "0",
      appliesto: "inlineLevelBoxesAndSVGTextContentElements",
      computed: "theSpecifiedKeywordOrAComputedLengthPercentageValue",
      order: "perGrammar",
      status: "standard"
    },
    "baseline-source": {
      syntax: "auto | first | last",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "auto",
      appliesto: "inlineLevelBoxes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/baseline-source"
    },
    "block-size": {
      syntax: "<'width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "blockSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "auto",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsWidthAndHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/block-size"
    },
    border: {
      syntax: "<line-width> || <line-style> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-width",
        "border-style",
        "border-color"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-width",
        "border-style",
        "border-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-width",
        "border-style",
        "border-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border"
    },
    "border-block": {
      syntax: "<'border-block-start'>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-block-width",
        "border-block-style",
        "border-block-color"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-block-width",
        "border-block-style",
        "border-block-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-block-width",
        "border-block-style",
        "border-block-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block"
    },
    "border-block-color": {
      syntax: "<'border-top-color'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-color"
    },
    "border-block-end": {
      syntax: "<'border-top-width'> || <'border-top-style'> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-block-end-color",
        "border-block-end-style",
        "border-block-end-width"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-top-width",
        "border-top-style",
        "border-top-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-top-width",
        "border-top-style",
        "border-top-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-end"
    },
    "border-block-end-color": {
      syntax: "<'border-top-color'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-end-color"
    },
    "border-block-end-style": {
      syntax: "<'border-top-style'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-end-style"
    },
    "border-block-end-width": {
      syntax: "<'border-top-width'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-end-width"
    },
    "border-block-start": {
      syntax: "<'border-top-width'> || <'border-top-style'> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-block-start-color",
        "border-block-start-style",
        "border-block-start-width"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-width",
        "border-style",
        "color"
      ],
      appliesto: "allElements",
      computed: [
        "border-width",
        "border-style",
        "border-block-start-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-start"
    },
    "border-block-start-color": {
      syntax: "<'border-top-color'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-start-color"
    },
    "border-block-start-style": {
      syntax: "<'border-top-style'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-start-style"
    },
    "border-block-start-width": {
      syntax: "<'border-top-width'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-start-width"
    },
    "border-block-style": {
      syntax: "<'border-top-style'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-style"
    },
    "border-block-width": {
      syntax: "<'border-top-width'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-block-width"
    },
    "border-bottom": {
      syntax: "<line-width> || <line-style> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-bottom-color",
        "border-bottom-style",
        "border-bottom-width"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-bottom-width",
        "border-bottom-style",
        "border-bottom-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-bottom-width",
        "border-bottom-style",
        "border-bottom-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom"
    },
    "border-bottom-color": {
      syntax: "<'border-top-color'>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom-color"
    },
    "border-bottom-left-radius": {
      syntax: "<length-percentage [0,∞]>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom-left-radius"
    },
    "border-bottom-right-radius": {
      syntax: "<length-percentage [0,∞]>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom-right-radius"
    },
    "border-bottom-style": {
      syntax: "<line-style>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom-style"
    },
    "border-bottom-width": {
      syntax: "<line-width>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthOr0IfBorderBottomStyleNoneOrHidden",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-bottom-width"
    },
    "border-collapse": {
      syntax: "separate | collapse",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Table"
      ],
      initial: "separate",
      appliesto: "tableElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-collapse"
    },
    "border-color": {
      syntax: "<color>{1,4}",
      media: "visual",
      inherited: false,
      animationType: [
        "border-bottom-color",
        "border-left-color",
        "border-right-color",
        "border-top-color"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-top-color",
        "border-right-color",
        "border-bottom-color",
        "border-left-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-bottom-color",
        "border-left-color",
        "border-right-color",
        "border-top-color"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-color"
    },
    "border-end-end-radius": {
      syntax: "<'border-top-left-radius'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-end-end-radius"
    },
    "border-end-start-radius": {
      syntax: "<'border-top-left-radius'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-end-start-radius"
    },
    "border-image": {
      syntax: "<'border-image-source'> || <'border-image-slice'> [ / <'border-image-width'> | / <'border-image-width'>? / <'border-image-outset'> ]? || <'border-image-repeat'>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-image-outset",
        "border-image-repeat",
        "border-image-slice",
        "border-image-source",
        "border-image-width"
      ],
      percentages: [
        "border-image-slice",
        "border-image-width"
      ],
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-image-source",
        "border-image-slice",
        "border-image-width",
        "border-image-outset",
        "border-image-repeat"
      ],
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: [
        "border-image-outset",
        "border-image-repeat",
        "border-image-slice",
        "border-image-source",
        "border-image-width"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image"
    },
    "border-image-outset": {
      syntax: "[ <length [0,∞]> | <number [0,∞]> ]{1,4}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0",
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image-outset"
    },
    "border-image-repeat": {
      syntax: "[ stretch | repeat | round | space ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "stretch",
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image-repeat"
    },
    "border-image-slice": {
      syntax: "[ <number [0,∞]> | <percentage [0,∞]> ]{1,4} && fill?",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSizeOfBorderImage",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "100%",
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: "oneToFourPercentagesOrAbsoluteLengthsPlusFill",
      order: "percentagesOrLengthsFollowedByFill",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image-slice"
    },
    "border-image-source": {
      syntax: "none | <image>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: "noneOrImageWithAbsoluteURI",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image-source"
    },
    "border-image-width": {
      syntax: "[ <length-percentage [0,∞]> | <number [0,∞]> | auto ]{1,4}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToWidthOrHeightOfBorderImageArea",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "1",
      appliesto: "allElementsExceptTableElementsWhenCollapse",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-image-width"
    },
    "border-inline": {
      syntax: "<'border-block-start'>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-inline-color",
        "border-inline-style",
        "border-inline-width"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-inline-width",
        "border-inline-style",
        "border-inline-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-inline-width",
        "border-inline-style",
        "border-inline-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline"
    },
    "border-inline-color": {
      syntax: "<'border-top-color'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-color"
    },
    "border-inline-end": {
      syntax: "<'border-top-width'> || <'border-top-style'> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-inline-end-color",
        "border-inline-end-style",
        "border-inline-end-width"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-width",
        "border-style",
        "color"
      ],
      appliesto: "allElements",
      computed: [
        "border-width",
        "border-style",
        "border-inline-end-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-end"
    },
    "border-inline-end-color": {
      syntax: "<'border-top-color'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-end-color"
    },
    "border-inline-end-style": {
      syntax: "<'border-top-style'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-end-style"
    },
    "border-inline-end-width": {
      syntax: "<'border-top-width'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-end-width"
    },
    "border-inline-start": {
      syntax: "<'border-top-width'> || <'border-top-style'> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-inline-start-color",
        "border-inline-start-style",
        "border-inline-start-width"
      ],
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "border-width",
        "border-style",
        "color"
      ],
      appliesto: "allElements",
      computed: [
        "border-width",
        "border-style",
        "border-inline-start-color"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-start"
    },
    "border-inline-start-color": {
      syntax: "<'border-top-color'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-start-color"
    },
    "border-inline-start-style": {
      syntax: "<'border-top-style'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-start-style"
    },
    "border-inline-start-width": {
      syntax: "<'border-top-width'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-start-width"
    },
    "border-inline-style": {
      syntax: "<'border-top-style'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-style"
    },
    "border-inline-width": {
      syntax: "<'border-top-width'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthZeroIfBorderStyleNoneOrHidden",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-inline-width"
    },
    "border-left": {
      syntax: "<line-width> || <line-style> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-left-color",
        "border-left-style",
        "border-left-width"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-left-width",
        "border-left-style",
        "border-left-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-left-width",
        "border-left-style",
        "border-left-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-left"
    },
    "border-left-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-left-color"
    },
    "border-left-style": {
      syntax: "<line-style>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-left-style"
    },
    "border-left-width": {
      syntax: "<line-width>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthOr0IfBorderLeftStyleNoneOrHidden",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-left-width"
    },
    "border-radius": {
      syntax: "<length-percentage [0,∞]>{1,4} [ / <length-percentage [0,∞]>{1,4} ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "border-top-left-radius",
        "border-top-right-radius",
        "border-bottom-right-radius",
        "border-bottom-left-radius"
      ],
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-top-left-radius",
        "border-top-right-radius",
        "border-bottom-right-radius",
        "border-bottom-left-radius"
      ],
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: [
        "border-bottom-left-radius",
        "border-bottom-right-radius",
        "border-top-left-radius",
        "border-top-right-radius"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-radius"
    },
    "border-right": {
      syntax: "<line-width> || <line-style> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-right-color",
        "border-right-style",
        "border-right-width"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-right-width",
        "border-right-style",
        "border-right-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-right-width",
        "border-right-style",
        "border-right-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-right"
    },
    "border-right-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-right-color"
    },
    "border-right-style": {
      syntax: "<line-style>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-right-style"
    },
    "border-right-width": {
      syntax: "<line-width>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthOr0IfBorderRightStyleNoneOrHidden",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-right-width"
    },
    "border-spacing": {
      syntax: "<length>{1,2}",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Table"
      ],
      initial: "0",
      appliesto: "tableElements",
      computed: "twoAbsoluteLengths",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-spacing"
    },
    "border-start-end-radius": {
      syntax: "<'border-top-left-radius'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-start-end-radius"
    },
    "border-start-start-radius": {
      syntax: "<'border-top-left-radius'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-start-start-radius"
    },
    "border-style": {
      syntax: "<line-style>{1,4}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-top-style",
        "border-right-style",
        "border-bottom-style",
        "border-left-style"
      ],
      appliesto: "allElements",
      computed: [
        "border-bottom-style",
        "border-left-style",
        "border-right-style",
        "border-top-style"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-style"
    },
    "border-top": {
      syntax: "<line-width> || <line-style> || <color>",
      media: "visual",
      inherited: false,
      animationType: [
        "border-top-color",
        "border-top-style",
        "border-top-width"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-top-width",
        "border-top-style",
        "border-top-color"
      ],
      appliesto: "allElements",
      computed: [
        "border-top-width",
        "border-top-style",
        "border-top-color"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top"
    },
    "border-top-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top-color"
    },
    "border-top-left-radius": {
      syntax: "<length-percentage [0,∞]>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top-left-radius"
    },
    "border-top-right-radius": {
      syntax: "<length-percentage [0,∞]>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfBorderBox",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "0",
      appliesto: "allElementsUAsNotRequiredWhenCollapse",
      computed: "twoAbsoluteLengthOrPercentages",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top-right-radius"
    },
    "border-top-style": {
      syntax: "<line-style>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top-style"
    },
    "border-top-width": {
      syntax: "<line-width>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLengthOr0IfBorderTopStyleNoneOrHidden",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-top-width"
    },
    "border-width": {
      syntax: "<line-width>{1,4}",
      media: "visual",
      inherited: false,
      animationType: [
        "border-bottom-width",
        "border-left-width",
        "border-right-width",
        "border-top-width"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "border-top-width",
        "border-right-width",
        "border-bottom-width",
        "border-left-width"
      ],
      appliesto: "allElements",
      computed: [
        "border-bottom-width",
        "border-left-width",
        "border-right-width",
        "border-top-width"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/border-width"
    },
    bottom: {
      syntax: "auto | <length-percentage> | <anchor()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToContainingBlockHeight",
      groups: [
        "CSS Anchor Positioning",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/bottom"
    },
    "box-align": {
      syntax: "start | center | end | baseline | stretch",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "stretch",
      appliesto: "elementsWithDisplayBoxOrInlineBox",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-align"
    },
    "box-decoration-break": {
      syntax: "slice | clone",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "slice",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-decoration-break"
    },
    "box-direction": {
      syntax: "normal | reverse | inherit",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "normal",
      appliesto: "elementsWithDisplayBoxOrInlineBox",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-direction"
    },
    "box-flex": {
      syntax: "<number>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "0",
      appliesto: "directChildrenOfElementsWithDisplayMozBoxMozInlineBox",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-flex"
    },
    "box-flex-group": {
      syntax: "<integer>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "1",
      appliesto: "inFlowChildrenOfBoxElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-flex-group"
    },
    "box-lines": {
      syntax: "single | multiple",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "single",
      appliesto: "boxElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-lines"
    },
    "box-ordinal-group": {
      syntax: "<integer>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "1",
      appliesto: "childrenOfBoxElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-ordinal-group"
    },
    "box-orient": {
      syntax: "horizontal | vertical | inline-axis | block-axis | inherit",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "inline-axis",
      appliesto: "elementsWithDisplayBoxOrInlineBox",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-orient"
    },
    "box-pack": {
      syntax: "start | center | end | justify",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions",
        "WebKit Extensions"
      ],
      initial: "start",
      appliesto: "elementsWithDisplayMozBoxMozInlineBox",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-pack"
    },
    "box-shadow": {
      syntax: "none | <shadow>#",
      media: "visual",
      inherited: false,
      animationType: "shadowList",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "absoluteLengthsSpecifiedColorAsSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-shadow"
    },
    "box-sizing": {
      syntax: "content-box | border-box",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "content-box",
      appliesto: "allElementsAcceptingWidthOrHeight",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/box-sizing"
    },
    "break-after": {
      syntax: "auto | avoid | always | all | avoid-page | page | left | right | recto | verso | avoid-column | column | avoid-region | region",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "auto",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/break-after"
    },
    "break-before": {
      syntax: "auto | avoid | always | all | avoid-page | page | left | right | recto | verso | avoid-column | column | avoid-region | region",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "auto",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/break-before"
    },
    "break-inside": {
      syntax: "auto | avoid | avoid-page | avoid-column | avoid-region",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "auto",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/break-inside"
    },
    "caption-side": {
      syntax: "top | bottom",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Table"
      ],
      initial: "top",
      appliesto: "tableCaptionElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/caption-side"
    },
    caret: {
      syntax: "<'caret-color'> || <'caret-animation'> || <'caret-shape'>",
      media: "interactive",
      inherited: true,
      animationType: [
        "caret-color",
        "caret-animation",
        "caret-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: [
        "caret-color",
        "caret-animation",
        "caret-shape"
      ],
      appliesto: "textOrElementsThatAcceptInput",
      computed: [
        "caret-color",
        "caret-animation",
        "caret-shape"
      ],
      order: "perGrammar",
      status: "standard"
    },
    "caret-animation": {
      syntax: "auto | manual",
      media: "interactive",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "textOrElementsThatAcceptInput",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/caret-animation"
    },
    "caret-color": {
      syntax: "auto | <color>",
      media: "interactive",
      inherited: true,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "textOrElementsThatAcceptInput",
      computed: "asAutoOrColor",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/caret-color"
    },
    "caret-shape": {
      syntax: "auto | bar | block | underscore",
      media: "interactive",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "textOrElementsThatAcceptInput",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard"
    },
    clear: {
      syntax: "none | left | right | both | inline-start | inline-end",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Positioned Layout"
      ],
      initial: "none",
      appliesto: "blockLevelElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/clear"
    },
    clip: {
      syntax: "<shape> | auto",
      media: "visual",
      inherited: false,
      animationType: "rectangle",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "auto",
      appliesto: "absolutelyPositionedElements",
      computed: "autoOrRectangle",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/clip"
    },
    "clip-path": {
      syntax: "<clip-source> | [ <basic-shape> || <geometry-box> ] | none",
      media: "visual",
      inherited: false,
      animationType: "basicShapeOtherwiseNo",
      percentages: "referToReferenceBoxWhenSpecifiedOtherwiseBorderBox",
      groups: [
        "CSS Masking"
      ],
      initial: "none",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedURLsAbsolute",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/clip-path"
    },
    "clip-rule": {
      syntax: "nonzero | evenodd",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "nonzero",
      appliesto: "limitedSVGElementsGraphics",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/clip-rule"
    },
    color: {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Color"
      ],
      initial: "canvastext",
      appliesto: "allElementsAndText",
      computed: "computedColor",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/color"
    },
    "color-interpolation-filters": {
      syntax: "auto | sRGB | linearRGB",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "linearRGB",
      appliesto: "limitedSVGElementsFilterPrimitives",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/color-interpolation-filters"
    },
    "color-scheme": {
      syntax: "normal | [ light | dark | <custom-ident> ]+ && only?",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Color"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/color-scheme"
    },
    "column-count": {
      syntax: "<integer> | auto",
      media: "visual",
      inherited: false,
      animationType: "integer",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "auto",
      appliesto: "blockContainersExceptTableWrappers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-count"
    },
    "column-fill": {
      syntax: "auto | balance",
      media: "visualInContinuousMediaNoEffectInOverflowColumns",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "balance",
      appliesto: "multicolElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-fill"
    },
    "column-gap": {
      syntax: "normal | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Box Alignment",
        "CSS Multi-column Layout"
      ],
      initial: "normal",
      appliesto: "multiColumnElementsFlexContainersGridContainers",
      computed: "asSpecifiedWithLengthsAbsoluteAndNormalComputingToZeroExceptMultiColumn",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-gap"
    },
    "column-height": {
      syntax: "auto | <length [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing",
        "CSS Multi-column Layout"
      ],
      initial: "auto",
      appliesto: "blockContainersExceptTableWrappers",
      computed: "autoOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-height"
    },
    "column-rule": {
      syntax: "<'column-rule-width'> || <'column-rule-style'> || <'column-rule-color'>",
      media: "visual",
      inherited: false,
      animationType: [
        "column-rule-color",
        "column-rule-style",
        "column-rule-width"
      ],
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: [
        "column-rule-width",
        "column-rule-style",
        "column-rule-color"
      ],
      appliesto: "multicolElements",
      computed: [
        "column-rule-color",
        "column-rule-style",
        "column-rule-width"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-rule"
    },
    "column-rule-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "currentcolor",
      appliesto: "multicolElements",
      computed: "computedColor",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-rule-color"
    },
    "column-rule-style": {
      syntax: "<'border-style'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "none",
      appliesto: "multicolElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-rule-style"
    },
    "column-rule-width": {
      syntax: "<'border-width'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "medium",
      appliesto: "multicolElements",
      computed: "absoluteLength0IfColumnRuleStyleNoneOrHidden",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-rule-width"
    },
    "column-span": {
      syntax: "none | all",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: "none",
      appliesto: "inFlowBlockLevelElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-span"
    },
    "column-width": {
      syntax: "auto | <length [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing",
        "CSS Multi-column Layout"
      ],
      initial: "auto",
      appliesto: "blockContainersExceptTableWrappers",
      computed: "autoOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-width"
    },
    "column-wrap": {
      syntax: "auto | nowrap | wrap",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Sizing",
        "CSS Multi-column Layout"
      ],
      initial: "auto",
      appliesto: "multicolElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-wrap"
    },
    columns: {
      syntax: "[ <'column-width'> || <'column-count'> ] [ / <'column-height'> ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "column-width",
        "column-count",
        "column-height"
      ],
      percentages: "no",
      groups: [
        "CSS Multi-column Layout"
      ],
      initial: [
        "column-width",
        "column-count",
        "column-height"
      ],
      appliesto: "blockContainersExceptTableWrappers",
      computed: [
        "column-width",
        "column-count",
        "column-height"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/columns"
    },
    contain: {
      syntax: "none | strict | content | [ [ size || inline-size ] || layout || style || paint ]",
      media: "all",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Containment"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain"
    },
    "contain-intrinsic-block-size": {
      syntax: "auto? [ none | <length> ]",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: "asSpecifiedWithLengthValuesComputed",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain-intrinsic-block-size"
    },
    "contain-intrinsic-height": {
      syntax: "auto? [ none | <length> ]",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: "asSpecifiedWithLengthValuesComputed",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain-intrinsic-height"
    },
    "contain-intrinsic-inline-size": {
      syntax: "auto? [ none | <length> ]",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: "asSpecifiedWithLengthValuesComputed",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain-intrinsic-inline-size"
    },
    "contain-intrinsic-size": {
      syntax: "[ auto? [ none | <length> ] ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "contain-intrinsic-width",
        "contain-intrinsic-height"
      ],
      percentages: [
        "contain-intrinsic-width",
        "contain-intrinsic-height"
      ],
      groups: [
        "CSS Box Sizing"
      ],
      initial: [
        "contain-intrinsic-width",
        "contain-intrinsic-height"
      ],
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: [
        "contain-intrinsic-width",
        "contain-intrinsic-height"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain-intrinsic-size"
    },
    "contain-intrinsic-width": {
      syntax: "auto? [ none | <length> ]",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: "asSpecifiedWithLengthValuesComputed",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/contain-intrinsic-width"
    },
    container: {
      syntax: "<'container-name'> [ / <'container-type'> ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "container-name",
        "container-type"
      ],
      percentages: [
        "container-name",
        "container-type"
      ],
      groups: [
        "CSS Conditional Rules"
      ],
      initial: [
        "container-name",
        "container-type"
      ],
      appliesto: "allElements",
      computed: [
        "container-name",
        "container-type"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/container"
    },
    "container-name": {
      syntax: "none | <custom-ident>+",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Conditional Rules"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "noneOrOrderedListOfIdentifiers",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/container-name"
    },
    "container-type": {
      syntax: "normal | [ [ size | inline-size ] || scroll-state ]",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Conditional Rules"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/container-type"
    },
    content: {
      syntax: "normal | none | [ <content-replacement> | <content-list> ] [ / [ <string> | <counter> | <attr()> ]+ ]?",
      media: "all",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Generated Content"
      ],
      initial: "normal",
      appliesto: "allElementsTreeAbidingPseudoElementsPageMarginBoxes",
      computed: "normalOnElementsForPseudosNoneAbsoluteURIStringOrAsSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/content"
    },
    "content-visibility": {
      syntax: "visible | auto | hidden",
      media: "all",
      inherited: false,
      animationType: "discreteButVisibleForDurationWhenAnimatedHidden",
      percentages: "no",
      groups: [
        "CSS Containment"
      ],
      initial: "visible",
      appliesto: "elementsForWhichSizeContainmentCanApply",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/content-visibility"
    },
    "corner-block-end-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-end-start-shape",
        "corner-end-end-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-end-start-shape",
        "corner-end-end-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-end-start-shape",
        "corner-end-end-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-block-end-shape"
    },
    "corner-block-start-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-block-start-shape"
    },
    "corner-bottom-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-bottom-shape"
    },
    "corner-bottom-left-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-bottom-left-shape"
    },
    "corner-bottom-right-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-bottom-right-shape"
    },
    "corner-end-end-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-end-end-shape"
    },
    "corner-end-start-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-end-start-shape"
    },
    "corner-inline-end-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-start-end-shape",
        "corner-end-end-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-start-end-shape",
        "corner-end-end-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-start-end-shape",
        "corner-end-end-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-inline-end-shape"
    },
    "corner-inline-start-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-start-start-shape",
        "corner-start-end-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-inline-start-shape"
    },
    "corner-left-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-top-left-shape",
        "corner-bottom-left-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-top-left-shape",
        "corner-bottom-left-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-top-left-shape",
        "corner-bottom-left-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-left-shape"
    },
    "corner-right-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-top-right-shape",
        "corner-bottom-right-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-top-right-shape",
        "corner-bottom-right-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-top-right-shape",
        "corner-bottom-right-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-right-shape"
    },
    "corner-shape": {
      syntax: "<corner-shape-value>{1,4}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-top-left-shape",
        "corner-top-right-shape",
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-top-left-shape",
        "corner-top-right-shape",
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-top-left-shape",
        "corner-top-right-shape",
        "corner-bottom-left-shape",
        "corner-bottom-right-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-shape"
    },
    "corner-start-start-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-start-start-shape"
    },
    "corner-start-end-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-start-end-shape"
    },
    "corner-top-shape": {
      syntax: "<corner-shape-value>{1,2}",
      media: "visual",
      inherited: false,
      animationType: [
        "corner-top-left-shape",
        "corner-top-right-shape"
      ],
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: [
        "corner-top-left-shape",
        "corner-top-right-shape"
      ],
      appliesto: "allElements",
      computed: [
        "corner-top-left-shape",
        "corner-top-right-shape"
      ],
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-top-shape"
    },
    "corner-top-left-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-top-left-shape"
    },
    "corner-top-right-shape": {
      syntax: "<corner-shape-value>",
      media: "visual",
      inherited: false,
      animationType: "superellipseInterpolation",
      percentages: "no",
      groups: [
        "CSS Backgrounds and Borders"
      ],
      initial: "round",
      appliesto: "allElements",
      computed: "correspondingSuperellipse",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/corner-top-right-shape"
    },
    "counter-increment": {
      syntax: "[ <counter-name> <integer>? ]+ | none",
      media: "all",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/counter-increment"
    },
    "counter-reset": {
      syntax: "[ <counter-name> <integer>? | <reversed-counter-name> <integer>? ]+ | none",
      media: "all",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/counter-reset"
    },
    "counter-set": {
      syntax: "[ <counter-name> <integer>? ]+ | none",
      media: "all",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/counter-set"
    },
    cursor: {
      syntax: "[ [ <url> [ <x> <y> ]? , ]* <cursor-predefined> ]",
      media: [
        "visual",
        "interactive"
      ],
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecifiedURLsAbsolute",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/cursor"
    },
    cx: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportWidth",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsEllipse",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/cx"
    },
    cy: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportHeight",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsEllipse",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/cy"
    },
    d: {
      syntax: "none | path(<string>)",
      media: "visual",
      inherited: false,
      animationType: "basicShapeOtherwiseNo",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsPath",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/d"
    },
    direction: {
      syntax: "ltr | rtl",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Writing Modes"
      ],
      initial: "ltr",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/direction"
    },
    display: {
      syntax: "[ <display-outside> || <display-inside> ] | <display-listitem> | <display-internal> | <display-box> | <display-legacy>",
      media: "all",
      inherited: false,
      animationType: "discreteButVisibleForDurationWhenAnimatedNone",
      percentages: "no",
      groups: [
        "CSS Display"
      ],
      initial: "inline",
      appliesto: "allElements",
      computed: "asSpecifiedExceptPositionedFloatingAndRootElementsKeywordMaybeDifferent",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/display"
    },
    "dominant-baseline": {
      syntax: "auto | text-bottom | alphabetic | ideographic | middle | central | mathematical | hanging | text-top",
      media: "all",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline",
        "Scalable Vector Graphics"
      ],
      initial: "auto",
      appliesto: "blockContainersFlexContainersGridContainersInlineBoxesTableRowsSVGTextContentElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/dominant-baseline"
    },
    "dynamic-range-limit": {
      syntax: "standard | no-limit | constrained | <dynamic-range-limit-mix()>",
      media: "visual",
      inherited: true,
      animationType: "byDynamicRangeLimitMix",
      percentages: "no",
      groups: [
        "CSS Color"
      ],
      initial: "no-limit",
      appliesto: "allElements",
      computed: "computedValueForDynamicRangeLimit",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/dynamic-range-limit"
    },
    "empty-cells": {
      syntax: "show | hide",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Table"
      ],
      initial: "show",
      appliesto: "tableCellElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/empty-cells"
    },
    "field-sizing": {
      syntax: "content | fixed",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "fixed",
      appliesto: "elementsWithDefaultPreferredSize",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/field-sizing"
    },
    fill: {
      syntax: "<paint>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "black",
      appliesto: "limitedSVGElementsShapeText",
      computed: "asColorOrAbsoluteURL",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/fill"
    },
    "fill-opacity": {
      syntax: "<'opacity'>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "mapToRange0To1",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "1",
      appliesto: "limitedSVGElementsShapeText",
      computed: "specifiedValueNumberClipped0To1",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/fill-opacity"
    },
    "fill-rule": {
      syntax: "nonzero | evenodd",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "nonzero",
      appliesto: "limitedSVGElementsShapeText",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/fill-rule"
    },
    filter: {
      syntax: "none | <filter-value-list>",
      media: "visual",
      inherited: false,
      animationType: "filterList",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "none",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/filter"
    },
    flex: {
      syntax: "none | [ <'flex-grow'> <'flex-shrink'>? || <'flex-basis'> ]",
      media: "visual",
      inherited: false,
      animationType: [
        "flex-grow",
        "flex-shrink",
        "flex-basis"
      ],
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: [
        "flex-grow",
        "flex-shrink",
        "flex-basis"
      ],
      appliesto: "flexItemsAndInFlowPseudos",
      computed: [
        "flex-grow",
        "flex-shrink",
        "flex-basis"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex"
    },
    "flex-basis": {
      syntax: "content | <'width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToFlexContainersInnerMainSize",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: "auto",
      appliesto: "flexItemsAndInFlowPseudos",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "lengthOrPercentageBeforeKeywordIfBothPresent",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-basis"
    },
    "flex-direction": {
      syntax: "row | row-reverse | column | column-reverse",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: "row",
      appliesto: "flexContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-direction"
    },
    "flex-flow": {
      syntax: "<'flex-direction'> || <'flex-wrap'>",
      media: "visual",
      inherited: false,
      animationType: [
        "flex-direction",
        "flex-wrap"
      ],
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: [
        "flex-direction",
        "flex-wrap"
      ],
      appliesto: "flexContainers",
      computed: [
        "flex-direction",
        "flex-wrap"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-flow"
    },
    "flex-grow": {
      syntax: "<number>",
      media: "visual",
      inherited: false,
      animationType: "number",
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: "0",
      appliesto: "flexItemsAndInFlowPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-grow"
    },
    "flex-shrink": {
      syntax: "<number>",
      media: "visual",
      inherited: false,
      animationType: "number",
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: "1",
      appliesto: "flexItemsAndInFlowPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-shrink"
    },
    "flex-wrap": {
      syntax: "nowrap | wrap | wrap-reverse",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Flexible Box Layout"
      ],
      initial: "nowrap",
      appliesto: "flexContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flex-wrap"
    },
    float: {
      syntax: "left | right | none | inline-start | inline-end",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Positioned Layout"
      ],
      initial: "none",
      appliesto: "allElementsNoEffectIfDisplayNone",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/float"
    },
    "flood-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "black",
      appliesto: "limitedSVGElementsFloodAndDropShadow",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flood-color"
    },
    "flood-opacity": {
      syntax: "<'opacity'>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "black",
      appliesto: "limitedSVGElementsFloodAndDropShadow",
      computed: "specifiedValueClipped0To1",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/flood-opacity"
    },
    font: {
      syntax: "[ [ <'font-style'> || <font-variant-css2> || <'font-weight'> || <font-width-css3> ]? <'font-size'> [ / <'line-height'> ]? <'font-family'># ] | <system-family-name>",
      media: "visual",
      inherited: true,
      animationType: [
        "font-style",
        "font-variant",
        "font-weight",
        "font-stretch",
        "font-size",
        "line-height",
        "font-family"
      ],
      percentages: [
        "font-size",
        "line-height"
      ],
      groups: [
        "CSS Fonts"
      ],
      initial: [
        "font-style",
        "font-variant",
        "font-weight",
        "font-stretch",
        "font-size",
        "line-height",
        "font-family"
      ],
      appliesto: "allElementsAndText",
      computed: [
        "font-style",
        "font-variant",
        "font-weight",
        "font-stretch",
        "font-size",
        "line-height",
        "font-family"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font"
    },
    "font-family": {
      syntax: "[ <family-name> | <generic-family> ]#",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "dependsOnUserAgent",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-family"
    },
    "font-feature-settings": {
      syntax: "normal | <feature-tag-value>#",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-feature-settings"
    },
    "font-kerning": {
      syntax: "auto | normal | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-kerning"
    },
    "font-language-override": {
      syntax: "normal | <string>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-language-override"
    },
    "font-optical-sizing": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-optical-sizing"
    },
    "font-palette": {
      syntax: "normal | light | dark | <palette-identifier> | <palette-mix()>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-palette"
    },
    "font-size": {
      syntax: "<absolute-size> | <relative-size> | <length-percentage [0,∞]> | math",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "referToParentElementsFontSize",
      groups: [
        "CSS Fonts"
      ],
      initial: "medium",
      appliesto: "allElementsAndText",
      computed: "absoluteLength",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-size"
    },
    "font-size-adjust": {
      syntax: "none | [ ex-height | cap-height | ch-width | ic-width | ic-height ]? [ from-font | <number> ]",
      media: "visual",
      inherited: true,
      animationType: "number",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "none",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-size-adjust"
    },
    "font-smooth": {
      syntax: "auto | never | always | <absolute-size> | <length>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-smooth"
    },
    "font-stretch": {
      syntax: "<font-stretch-absolute>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-stretch"
    },
    "font-style": {
      syntax: "normal | italic | oblique <angle>?",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueTypeNormalAnimatesAsObliqueZeroDeg",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-style"
    },
    "font-synthesis": {
      syntax: "none | [ weight || style || small-caps || position]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "weight style small-caps position ",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-synthesis"
    },
    "font-synthesis-position": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "none",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-synthesis-position"
    },
    "font-synthesis-small-caps": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-synthesis-small-caps"
    },
    "font-synthesis-style": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-synthesis-style"
    },
    "font-synthesis-weight": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-synthesis-weight"
    },
    "font-variant": {
      syntax: "normal | none | [ <common-lig-values> || <discretionary-lig-values> || <historical-lig-values> || <contextual-alt-values> || stylistic( <feature-value-name> ) || historical-forms || styleset( <feature-value-name># ) || character-variant( <feature-value-name># ) || swash( <feature-value-name> ) || ornaments( <feature-value-name> ) || annotation( <feature-value-name> ) || [ small-caps | all-small-caps | petite-caps | all-petite-caps | unicase | titling-caps ] || <numeric-figure-values> || <numeric-spacing-values> || <numeric-fraction-values> || ordinal || slashed-zero || <east-asian-variant-values> || <east-asian-width-values> || ruby ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant"
    },
    "font-variant-alternates": {
      syntax: "normal | [ stylistic( <feature-value-name> ) || historical-forms || styleset( <feature-value-name># ) || character-variant( <feature-value-name># ) || swash( <feature-value-name> ) || ornaments( <feature-value-name> ) || annotation( <feature-value-name> ) ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-alternates"
    },
    "font-variant-caps": {
      syntax: "normal | small-caps | all-small-caps | petite-caps | all-petite-caps | unicase | titling-caps",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-caps"
    },
    "font-variant-east-asian": {
      syntax: "normal | [ <east-asian-variant-values> || <east-asian-width-values> || ruby ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-east-asian"
    },
    "font-variant-emoji": {
      syntax: "normal | text | emoji | unicode",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-emoji"
    },
    "font-variant-ligatures": {
      syntax: "normal | none | [ <common-lig-values> || <discretionary-lig-values> || <historical-lig-values> || <contextual-alt-values> ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-ligatures"
    },
    "font-variant-numeric": {
      syntax: "normal | [ <numeric-figure-values> || <numeric-spacing-values> || <numeric-fraction-values> || ordinal || slashed-zero ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-numeric"
    },
    "font-variant-position": {
      syntax: "normal | sub | super",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variant-position"
    },
    "font-variation-settings": {
      syntax: "normal | [ <string> <number> ]#",
      media: "visual",
      inherited: true,
      animationType: "transform",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-variation-settings"
    },
    "font-weight": {
      syntax: "<font-weight-absolute> | bolder | lighter",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "keywordOrNumericalValueBolderLighterTransformedToRealValue",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/font-weight"
    },
    "font-width": {
      syntax: "normal | <percentage [0,∞]> | ultra-condensed | extra-condensed | condensed | semi-condensed | semi-expanded | expanded | extra-expanded | ultra-expanded",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Fonts"
      ],
      initial: "normal",
      appliesto: "allElementsAndText",
      computed: "percentage",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "experimental"
    },
    "forced-color-adjust": {
      syntax: "auto | none | preserve-parent-color",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Color"
      ],
      initial: "auto",
      appliesto: "allElementsAndText",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/forced-color-adjust"
    },
    gap: {
      syntax: "<'row-gap'> <'column-gap'>?",
      media: "visual",
      inherited: false,
      animationType: [
        "row-gap",
        "column-gap"
      ],
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: [
        "row-gap",
        "column-gap"
      ],
      appliesto: "multiColumnElementsFlexContainersGridContainers",
      computed: [
        "row-gap",
        "column-gap"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/gap"
    },
    grid: {
      syntax: "<'grid-template'> | <'grid-template-rows'> / [ auto-flow && dense? ] <'grid-auto-columns'>? | [ auto-flow && dense? ] <'grid-auto-rows'>? / <'grid-template-columns'>",
      media: "visual",
      inherited: false,
      animationType: [
        "grid-template-rows",
        "grid-template-columns",
        "grid-template-areas",
        "grid-auto-rows",
        "grid-auto-columns",
        "grid-auto-flow",
        "grid-column-gap",
        "grid-row-gap",
        "column-gap",
        "row-gap"
      ],
      percentages: [
        "grid-template-rows",
        "grid-template-columns",
        "grid-auto-rows",
        "grid-auto-columns"
      ],
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-template-rows",
        "grid-template-columns",
        "grid-template-areas",
        "grid-auto-rows",
        "grid-auto-columns",
        "grid-auto-flow",
        "grid-column-gap",
        "grid-row-gap",
        "column-gap",
        "row-gap"
      ],
      appliesto: "gridContainers",
      computed: [
        "grid-template-rows",
        "grid-template-columns",
        "grid-template-areas",
        "grid-auto-rows",
        "grid-auto-columns",
        "grid-auto-flow",
        "grid-column-gap",
        "grid-row-gap",
        "column-gap",
        "row-gap"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid"
    },
    "grid-area": {
      syntax: "<grid-line> [ / <grid-line> ]{0,3}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-row-start",
        "grid-column-start",
        "grid-row-end",
        "grid-column-end"
      ],
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: [
        "grid-row-start",
        "grid-column-start",
        "grid-row-end",
        "grid-column-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-area"
    },
    "grid-auto-columns": {
      syntax: "<track-size>+",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridContainers",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-auto-columns"
    },
    "grid-auto-flow": {
      syntax: "[ row | column ] || dense",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "row",
      appliesto: "gridContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-auto-flow"
    },
    "grid-auto-rows": {
      syntax: "<track-size>+",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridContainers",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-auto-rows"
    },
    "grid-column": {
      syntax: "<grid-line> [ / <grid-line> ]?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-column-start",
        "grid-column-end"
      ],
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: [
        "grid-column-start",
        "grid-column-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-column"
    },
    "grid-column-end": {
      syntax: "<grid-line>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-column-end"
    },
    "grid-column-gap": {
      syntax: "<length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "0",
      appliesto: "gridContainers",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/column-gap"
    },
    "grid-column-start": {
      syntax: "<grid-line>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-column-start"
    },
    "grid-gap": {
      syntax: "<'grid-row-gap'> <'grid-column-gap'>?",
      media: "visual",
      inherited: false,
      animationType: [
        "grid-row-gap",
        "grid-column-gap"
      ],
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-row-gap",
        "grid-column-gap"
      ],
      appliesto: "gridContainers",
      computed: [
        "grid-row-gap",
        "grid-column-gap"
      ],
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/gap"
    },
    "grid-row": {
      syntax: "<grid-line> [ / <grid-line> ]?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-row-start",
        "grid-row-end"
      ],
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: [
        "grid-row-start",
        "grid-row-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-row"
    },
    "grid-row-end": {
      syntax: "<grid-line>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-row-end"
    },
    "grid-row-gap": {
      syntax: "<length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "0",
      appliesto: "gridContainers",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/row-gap"
    },
    "grid-row-start": {
      syntax: "<grid-line>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "auto",
      appliesto: "gridItemsAndBoxesWithinGridContainer",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-row-start"
    },
    "grid-template": {
      syntax: "none | [ <'grid-template-rows'> / <'grid-template-columns'> ] | [ <line-names>? <string> <track-size>? <line-names>? ]+ [ / <explicit-track-list> ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "grid-template-columns",
        "grid-template-rows",
        "grid-template-areas"
      ],
      percentages: [
        "grid-template-columns",
        "grid-template-rows"
      ],
      groups: [
        "CSS Grid Layout"
      ],
      initial: [
        "grid-template-columns",
        "grid-template-rows",
        "grid-template-areas"
      ],
      appliesto: "gridContainers",
      computed: [
        "grid-template-columns",
        "grid-template-rows",
        "grid-template-areas"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-template"
    },
    "grid-template-areas": {
      syntax: "none | <string>+",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "none",
      appliesto: "gridContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-template-areas"
    },
    "grid-template-columns": {
      syntax: "none | <track-list> | <auto-track-list> | subgrid <line-name-list>?",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpcDifferenceLpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "none",
      appliesto: "gridContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-template-columns"
    },
    "grid-template-rows": {
      syntax: "none | <track-list> | <auto-track-list> | subgrid <line-name-list>?",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpcDifferenceLpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "none",
      appliesto: "gridContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-template-rows"
    },
    "hanging-punctuation": {
      syntax: "none | [ first || [ force-end | allow-end ] || last ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/hanging-punctuation"
    },
    height: {
      syntax: "auto | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "regardingHeightOfGeneratedBoxContainingBlockPercentagesRelativeToContainingBlock",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "auto",
      appliesto: "allElementsButNonReplacedAndTableColumns",
      computed: "percentageAutoOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/height"
    },
    "hyphenate-character": {
      syntax: "auto | <string>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/hyphenate-character"
    },
    "hyphenate-limit-chars": {
      syntax: "[ auto | <integer> ]{1,3}",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/hyphenate-limit-chars"
    },
    hyphens: {
      syntax: "none | manual | auto",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "manual",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/hyphens"
    },
    "image-orientation": {
      syntax: "from-image | <angle> | [ <angle>? flip ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Images"
      ],
      initial: "from-image",
      appliesto: "allElements",
      computed: "angleRoundedToNextQuarter",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/image-orientation"
    },
    "image-rendering": {
      syntax: "auto | crisp-edges | pixelated | smooth",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Images"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/image-rendering"
    },
    "image-resolution": {
      syntax: "[ from-image || <resolution> ] && snap?",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Images"
      ],
      initial: "1dppx",
      appliesto: "allElements",
      computed: "asSpecifiedWithExceptionOfResolution",
      order: "uniqueOrder",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/image-resolution"
    },
    "ime-mode": {
      syntax: "auto | normal | active | inactive | disabled",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "textFields",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "initial-letter": {
      syntax: "normal | [ <number> <integer>? ]",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "normal",
      appliesto: "firstLetterPseudoElementsAndInlineLevelFirstChildren",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/initial-letter"
    },
    "initial-letter-align": {
      syntax: "[ auto | alphabetic | hanging | ideographic ]",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "auto",
      appliesto: "firstLetterPseudoElementsAndInlineLevelFirstChildren",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "experimental"
    },
    "inline-size": {
      syntax: "<'width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "inlineSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "auto",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsWidthAndHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inline-size"
    },
    inset: {
      syntax: "<'top'>{1,4}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalHeightOrWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: [
        "top",
        "bottom",
        "left",
        "right"
      ],
      appliesto: "positionedElements",
      computed: [
        "top",
        "bottom",
        "left",
        "right"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset"
    },
    "inset-block": {
      syntax: "<'top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalHeightOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: [
        "inset-block-start",
        "inset-block-end"
      ],
      appliesto: "positionedElements",
      computed: [
        "inset-block-start",
        "inset-block-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-block"
    },
    "inset-block-end": {
      syntax: "<'top'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalHeightOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "sameAsBoxOffsets",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-block-end"
    },
    "inset-block-start": {
      syntax: "<'top'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalHeightOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "sameAsBoxOffsets",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-block-start"
    },
    "inset-inline": {
      syntax: "<'top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: [
        "inset-inline-start",
        "inset-inline-end"
      ],
      appliesto: "positionedElements",
      computed: [
        "inset-inline-start",
        "inset-inline-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-inline"
    },
    "inset-inline-end": {
      syntax: "<'top'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "sameAsBoxOffsets",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-inline-end"
    },
    "inset-inline-start": {
      syntax: "<'top'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "sameAsBoxOffsets",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/inset-inline-start"
    },
    "interpolate-size": {
      syntax: "numeric-only | allow-keywords",
      media: "none",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Values and Units"
      ],
      initial: "numeric-only",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/interpolate-size"
    },
    isolation: {
      syntax: "auto | isolate",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Compositing and Blending"
      ],
      initial: "auto",
      appliesto: "allElementsSVGContainerGraphicsAndGraphicsReferencingElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/isolation"
    },
    interactivity: {
      syntax: "auto | inert",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/interactivity"
    },
    "interest-delay": {
      syntax: "<'interest-delay-start'>{1,2}",
      media: "visual",
      inherited: true,
      animationType: [
        "interest-delay-start",
        "interest-delay-end"
      ],
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: [
        "interest-delay-start",
        "interest-delay-end"
      ],
      appliesto: "allElements",
      computed: [
        "interest-delay-start",
        "interest-delay-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/interest-delay-end"
    },
    "interest-delay-end": {
      syntax: "normal | <time>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "normalOrComputedTime",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/interest-delay-end"
    },
    "interest-delay-start": {
      syntax: "normal | <time>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "normalOrComputedTime",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/interest-delay-start"
    },
    "justify-content": {
      syntax: "normal | <content-distribution> | <overflow-position>? [ <content-position> | left | right ]",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment",
        "CSS Flexible Box Layout"
      ],
      initial: "normal",
      appliesto: "flexContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/justify-content"
    },
    "justify-items": {
      syntax: "normal | stretch | <baseline-position> | <overflow-position>? [ <self-position> | left | right ] | legacy | legacy && [ left | right | center ] | anchor-center",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: "legacy",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/justify-items"
    },
    "justify-self": {
      syntax: "auto | normal | stretch | <baseline-position> | <overflow-position>? [ <self-position> | left | right ] | anchor-center",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: "auto",
      appliesto: "blockLevelBoxesAndAbsolutelyPositionedBoxesAndGridItems",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/justify-self"
    },
    "justify-tracks": {
      syntax: "[ normal | <content-distribution> | <overflow-position>? [ <content-position> | left | right ] ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "normal",
      appliesto: "gridContainersWithMasonryLayoutInTheirInlineAxis",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    left: {
      syntax: "auto | <length-percentage> | <anchor()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/left"
    },
    "letter-spacing": {
      syntax: "normal | <length>",
      media: "visual",
      inherited: true,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "optimumValueOfAbsoluteLengthOrNormal",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/letter-spacing"
    },
    "lighting-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "Filter Effects"
      ],
      initial: "white",
      appliesto: "limitedSVGElementsLightSource",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/lighting-color"
    },
    "line-break": {
      syntax: "auto | loose | normal | strict | anywhere",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/line-break"
    },
    "line-clamp": {
      syntax: "none | <integer>",
      media: "visual",
      inherited: false,
      animationType: "integer",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "none",
      appliesto: "blockContainersExceptMultiColumnContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/line-clamp"
    },
    "line-height": {
      syntax: "normal | <number> | <length> | <percentage>",
      media: "visual",
      inherited: true,
      animationType: "numberOrLength",
      percentages: "referToElementFontSize",
      groups: [
        "CSS Inline"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "absoluteLengthOrAsSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/line-height"
    },
    "line-height-step": {
      syntax: "<length>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Rhythmic Sizing"
      ],
      initial: "0",
      appliesto: "blockContainers",
      computed: "absoluteLength",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/line-height-step"
    },
    "list-style": {
      syntax: "<'list-style-type'> || <'list-style-position'> || <'list-style-image'>",
      media: "visual",
      inherited: true,
      animationType: [
        "list-style-image",
        "list-style-position",
        "list-style-type"
      ],
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: [
        "list-style-type",
        "list-style-position",
        "list-style-image"
      ],
      appliesto: "listItems",
      computed: [
        "list-style-image",
        "list-style-position",
        "list-style-type"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/list-style"
    },
    "list-style-image": {
      syntax: "<image> | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "none",
      appliesto: "listItems",
      computed: "theKeywordListStyleImageNoneOrComputedValue",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/list-style-image"
    },
    "list-style-position": {
      syntax: "inside | outside",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "outside",
      appliesto: "listItems",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/list-style-position"
    },
    "list-style-type": {
      syntax: "<counter-style> | <string> | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Lists and Counters"
      ],
      initial: "disc",
      appliesto: "listItems",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/list-style-type"
    },
    margin: {
      syntax: "<'margin-top'>{1,4}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: [
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top"
      ],
      appliesto: "allElementsExceptTableDisplayTypes",
      computed: [
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin"
    },
    "margin-block": {
      syntax: "<'margin-top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "margin-block-start",
        "margin-block-end"
      ],
      appliesto: "sameAsMargin",
      computed: [
        "margin-block-start",
        "margin-block-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-block"
    },
    "margin-block-end": {
      syntax: "<'margin-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsMargin",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-block-end"
    },
    "margin-block-start": {
      syntax: "<'margin-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsMargin",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-block-start"
    },
    "margin-bottom": {
      syntax: "<length-percentage> | auto | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-bottom"
    },
    "margin-inline": {
      syntax: "<'margin-top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "margin-inline-start",
        "margin-inline-end"
      ],
      appliesto: "sameAsMargin",
      computed: [
        "margin-inline-start",
        "margin-inline-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-inline"
    },
    "margin-inline-end": {
      syntax: "<'margin-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsMargin",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-inline-end"
    },
    "margin-inline-start": {
      syntax: "<'margin-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "dependsOnLayoutModel",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsMargin",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-inline-start"
    },
    "margin-left": {
      syntax: "<length-percentage> | auto | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-left"
    },
    "margin-right": {
      syntax: "<length-percentage> | auto | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-right"
    },
    "margin-top": {
      syntax: "<length-percentage> | auto | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-top"
    },
    "margin-trim": {
      syntax: "none | in-flow | all",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Model"
      ],
      initial: "none",
      appliesto: "blockContainersAndMultiColumnContainers",
      computed: "asSpecified",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter"
      ],
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/margin-trim"
    },
    marker: {
      syntax: "none | <url>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: [
        "marker-start",
        "marker-mid",
        "marker-end"
      ],
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/marker"
    },
    "marker-end": {
      syntax: "none | <url>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecifiedURLsAbsolute",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/marker-end"
    },
    "marker-mid": {
      syntax: "none | <url>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecifiedURLsAbsolute",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/marker-mid"
    },
    "marker-start": {
      syntax: "none | <url>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecifiedURLsAbsolute",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/marker-start"
    },
    mask: {
      syntax: "<mask-layer>#",
      media: "visual",
      inherited: false,
      animationType: [
        "mask-image",
        "mask-mode",
        "mask-repeat",
        "mask-position",
        "mask-clip",
        "mask-origin",
        "mask-size",
        "mask-composite"
      ],
      percentages: [
        "mask-position"
      ],
      groups: [
        "CSS Masking"
      ],
      initial: [
        "mask-image",
        "mask-mode",
        "mask-repeat",
        "mask-position",
        "mask-clip",
        "mask-origin",
        "mask-size",
        "mask-composite"
      ],
      appliesto: "allElementsSVGContainerElements",
      computed: [
        "mask-image",
        "mask-mode",
        "mask-repeat",
        "mask-position",
        "mask-clip",
        "mask-origin",
        "mask-size",
        "mask-composite"
      ],
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask"
    },
    "mask-border": {
      syntax: "<'mask-border-source'> || <'mask-border-slice'> [ / <'mask-border-width'>? [ / <'mask-border-outset'> ]? ]? || <'mask-border-repeat'> || <'mask-border-mode'>",
      media: "visual",
      inherited: false,
      animationType: [
        "mask-border-mode",
        "mask-border-outset",
        "mask-border-repeat",
        "mask-border-slice",
        "mask-border-source",
        "mask-border-width"
      ],
      percentages: [
        "mask-border-slice",
        "mask-border-width"
      ],
      groups: [
        "CSS Masking"
      ],
      initial: [
        "mask-border-mode",
        "mask-border-outset",
        "mask-border-repeat",
        "mask-border-slice",
        "mask-border-source",
        "mask-border-width"
      ],
      appliesto: "allElementsSVGContainerElements",
      computed: [
        "mask-border-mode",
        "mask-border-outset",
        "mask-border-repeat",
        "mask-border-slice",
        "mask-border-source",
        "mask-border-width"
      ],
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border"
    },
    "mask-border-mode": {
      syntax: "luminance | alpha",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "alpha",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-mode"
    },
    "mask-border-outset": {
      syntax: "[ <length> | <number> ]{1,4}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "0",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-outset"
    },
    "mask-border-repeat": {
      syntax: "[ stretch | repeat | round | space ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "stretch",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-repeat"
    },
    "mask-border-slice": {
      syntax: "<number-percentage>{1,4} fill?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "referToSizeOfMaskBorderImage",
      groups: [
        "CSS Masking"
      ],
      initial: "0",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-slice"
    },
    "mask-border-source": {
      syntax: "none | <image>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "none",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedURLsAbsolute",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-source"
    },
    "mask-border-width": {
      syntax: "[ <length-percentage> | <number> | auto ]{1,4}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "relativeToMaskBorderImageArea",
      groups: [
        "CSS Masking"
      ],
      initial: "auto",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-border-width"
    },
    "mask-clip": {
      syntax: "[ <coord-box> | no-clip ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "border-box",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-clip"
    },
    "mask-composite": {
      syntax: "<compositing-operator>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "add",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-composite"
    },
    "mask-image": {
      syntax: "<mask-reference>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "none",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedURLsAbsolute",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-image"
    },
    "mask-mode": {
      syntax: "<masking-mode>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "match-source",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-mode"
    },
    "mask-origin": {
      syntax: "<coord-box>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "border-box",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-origin"
    },
    "mask-position": {
      syntax: "<position>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "referToSizeOfMaskPaintingArea",
      groups: [
        "CSS Masking"
      ],
      initial: "0% 0%",
      appliesto: "allElementsSVGContainerElements",
      computed: "consistsOfTwoKeywordsForOriginAndOffsets",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-position"
    },
    "mask-repeat": {
      syntax: "<repeat-style>#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "repeat",
      appliesto: "allElementsSVGContainerElements",
      computed: "consistsOfTwoDimensionKeywords",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-repeat"
    },
    "mask-size": {
      syntax: "<bg-size>#",
      media: "visual",
      inherited: false,
      animationType: "repeatableList",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "auto",
      appliesto: "allElementsSVGContainerElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-size"
    },
    "mask-type": {
      syntax: "luminance | alpha",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Masking"
      ],
      initial: "luminance",
      appliesto: "maskElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mask-type"
    },
    "masonry-auto-flow": {
      syntax: "[ pack | next ] || [ definite-first | ordered ]",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Grid Layout"
      ],
      initial: "pack",
      appliesto: "gridContainersWithMasonryLayout",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/grid-auto-flow"
    },
    "math-depth": {
      syntax: "auto-add | add(<integer>) | <integer>",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "MathML"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/math-depth"
    },
    "math-shift": {
      syntax: "normal | compact",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "MathML"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/math-shift"
    },
    "math-style": {
      syntax: "normal | compact",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "MathML"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/math-style"
    },
    "max-block-size": {
      syntax: "<'max-width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "blockSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsMaxWidthAndMaxHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/max-block-size"
    },
    "max-height": {
      syntax: "none | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "regardingHeightOfGeneratedBoxContainingBlockPercentagesNone",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "allElementsButNonReplacedAndTableColumns",
      computed: "percentageAsSpecifiedAbsoluteLengthOrNone",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/max-height"
    },
    "max-inline-size": {
      syntax: "<'max-width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "inlineSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "none",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsMaxWidthAndMaxHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/max-inline-size"
    },
    "max-lines": {
      syntax: "none | <integer>",
      media: "visual",
      inherited: false,
      animationType: "integer",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "none",
      appliesto: "blockContainersExceptMultiColumnContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental"
    },
    "max-width": {
      syntax: "none | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "none",
      appliesto: "allElementsButNonReplacedAndTableRows",
      computed: "percentageAsSpecifiedAbsoluteLengthOrNone",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/max-width"
    },
    "min-block-size": {
      syntax: "<'min-width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "blockSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsMinWidthAndMinHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/min-block-size"
    },
    "min-height": {
      syntax: "auto | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "regardingHeightOfGeneratedBoxContainingBlockPercentages0",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "auto",
      appliesto: "allElementsButNonReplacedAndTableColumns",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/min-height"
    },
    "min-inline-size": {
      syntax: "<'min-width'>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "inlineSizeOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "sameAsWidthAndHeight",
      computed: "sameAsMinWidthAndMinHeight",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/min-inline-size"
    },
    "min-width": {
      syntax: "auto | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "auto",
      appliesto: "allElementsButNonReplacedAndTableRows",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/min-width"
    },
    "mix-blend-mode": {
      syntax: "<blend-mode> | plus-darker | plus-lighter",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Compositing and Blending"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/mix-blend-mode"
    },
    "object-fit": {
      syntax: "fill | contain | cover | none | scale-down",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Images"
      ],
      initial: "fill",
      appliesto: "replacedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/object-fit"
    },
    "object-position": {
      syntax: "<position>",
      media: "visual",
      inherited: true,
      animationType: "repeatableList",
      percentages: "referToWidthAndHeightOfElement",
      groups: [
        "CSS Images"
      ],
      initial: "50% 50%",
      appliesto: "replacedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/object-position"
    },
    "object-view-box": {
      syntax: "none | <basic-shape-rect>",
      media: "visual",
      inherited: false,
      animationType: "asIfPossibleOtherwiseDiscrete",
      percentages: "no",
      groups: [
        "CSS Images"
      ],
      initial: "none",
      appliesto: "replacedElements",
      computed: "specifiedKeywordOrComputedFunction",
      order: "perGrammar",
      status: "experimental"
    },
    offset: {
      syntax: "[ <'offset-position'>? [ <'offset-path'> [ <'offset-distance'> || <'offset-rotate'> ]? ]? ]! [ / <'offset-anchor'> ]?",
      media: "visual",
      inherited: false,
      animationType: [
        "offset-position",
        "offset-path",
        "offset-distance",
        "offset-anchor",
        "offset-rotate"
      ],
      percentages: [
        "offset-position",
        "offset-distance",
        "offset-anchor"
      ],
      groups: [
        "Motion Path"
      ],
      initial: [
        "offset-position",
        "offset-path",
        "offset-distance",
        "offset-anchor",
        "offset-rotate"
      ],
      appliesto: "transformableElements",
      computed: [
        "offset-position",
        "offset-path",
        "offset-distance",
        "offset-anchor",
        "offset-rotate"
      ],
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset"
    },
    "offset-anchor": {
      syntax: "auto | <position>",
      media: "visual",
      inherited: false,
      animationType: "position",
      percentages: "relativeToWidthAndHeight",
      groups: [
        "Motion Path"
      ],
      initial: "auto",
      appliesto: "transformableElements",
      computed: "forLengthAbsoluteValueOtherwisePercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset-anchor"
    },
    "offset-distance": {
      syntax: "<length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToTotalPathLength",
      groups: [
        "Motion Path"
      ],
      initial: "0",
      appliesto: "transformableElements",
      computed: "forLengthAbsoluteValueOtherwisePercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset-distance"
    },
    "offset-path": {
      syntax: "none | <offset-path> || <coord-box>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "Motion Path"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset-path"
    },
    "offset-position": {
      syntax: "normal | auto | <position>",
      media: "visual",
      inherited: false,
      animationType: "position",
      percentages: "referToSizeOfContainingBlock",
      groups: [
        "Motion Path"
      ],
      initial: "normal",
      appliesto: "transformableElements",
      computed: "forLengthAbsoluteValueOtherwisePercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset-position"
    },
    "offset-rotate": {
      syntax: "[ auto | reverse ] || <angle>",
      media: "visual",
      inherited: false,
      animationType: "angleOrBasicShapeOrPath",
      percentages: "no",
      groups: [
        "Motion Path"
      ],
      initial: "auto",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/offset-rotate"
    },
    opacity: {
      syntax: "<opacity-value>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "mapToRange0To1",
      groups: [
        "CSS Color"
      ],
      initial: "1",
      appliesto: "allElements",
      computed: "specifiedValueNumberClipped0To1",
      order: "perGrammar",
      alsoAppliesTo: [
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/opacity"
    },
    order: {
      syntax: "<integer>",
      media: "visual",
      inherited: false,
      animationType: "integer",
      percentages: "no",
      groups: [
        "CSS Display"
      ],
      initial: "0",
      appliesto: "flexItemsGridItemsAbsolutelyPositionedContainerChildren",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/order"
    },
    orphans: {
      syntax: "<integer>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "2",
      appliesto: "blockContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/orphans"
    },
    outline: {
      syntax: "<'outline-width'> || <'outline-style'> || <'outline-color'>",
      media: [
        "visual",
        "interactive"
      ],
      inherited: false,
      animationType: [
        "outline-width",
        "outline-style",
        "outline-color"
      ],
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: [
        "outline-width",
        "outline-style",
        "outline-color"
      ],
      appliesto: "allElements",
      computed: [
        "outline-width",
        "outline-style",
        "outline-color"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/outline"
    },
    "outline-color": {
      syntax: "auto | <color>",
      media: [
        "visual",
        "interactive"
      ],
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "autoForTranslucentColorRGBAOtherwiseRGB",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/outline-color"
    },
    "outline-offset": {
      syntax: "<length>",
      media: [
        "visual",
        "interactive"
      ],
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/outline-offset"
    },
    "outline-style": {
      syntax: "auto | <outline-line-style>",
      media: [
        "visual",
        "interactive"
      ],
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/outline-style"
    },
    "outline-width": {
      syntax: "<line-width>",
      media: [
        "visual",
        "interactive"
      ],
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "medium",
      appliesto: "allElements",
      computed: "absoluteLength0ForNone",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/outline-width"
    },
    overflow: {
      syntax: "[ visible | hidden | clip | scroll | auto ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "visible",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: [
        "overflow-x",
        "overflow-y"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow"
    },
    "overflow-anchor": {
      syntax: "auto | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Anchoring"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-anchor"
    },
    "overflow-block": {
      syntax: "visible | hidden | clip | scroll | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "auto",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "asSpecifiedButVisibleOrClipReplacedToAutoOrHiddenIfOtherValueDifferent",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-block"
    },
    "overflow-clip-box": {
      syntax: "padding-box | content-box",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Mozilla Extensions"
      ],
      initial: "padding-box",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "nonstandard"
    },
    "overflow-clip-margin": {
      syntax: "<visual-box> || <length [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "0px",
      appliesto: "allElements",
      computed: "theComputedLengthAndVisualBox",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-clip-margin"
    },
    "overflow-inline": {
      syntax: "visible | hidden | clip | scroll | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "auto",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "asSpecifiedButVisibleOrClipReplacedToAutoOrHiddenIfOtherValueDifferent",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-inline"
    },
    "overflow-wrap": {
      syntax: "normal | break-word | anywhere",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "textElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-wrap"
    },
    "overflow-x": {
      syntax: "visible | hidden | clip | scroll | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "visible",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "asSpecifiedButVisibleOrClipReplacedToAutoOrHiddenIfOtherValueDifferent",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-x"
    },
    "overflow-y": {
      syntax: "visible | hidden | clip | scroll | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "visible",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "asSpecifiedButVisibleOrClipReplacedToAutoOrHiddenIfOtherValueDifferent",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-y"
    },
    overlay: {
      syntax: "none | auto",
      media: "visual",
      inherited: false,
      animationType: "discreteButVisibleForDurationWhenAnimatedNone",
      percentages: "no",
      groups: [
        "CSS Positioned Layout"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overlay"
    },
    "overscroll-behavior": {
      syntax: "[ contain | none | auto ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overscroll Behavior"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: [
        "overscroll-behavior-x",
        "overscroll-behavior-y"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overscroll-behavior"
    },
    "overscroll-behavior-block": {
      syntax: "contain | none | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overscroll Behavior"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overscroll-behavior-block"
    },
    "overscroll-behavior-inline": {
      syntax: "contain | none | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overscroll Behavior"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overscroll-behavior-inline"
    },
    "overscroll-behavior-x": {
      syntax: "contain | none | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overscroll Behavior"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overscroll-behavior-x"
    },
    "overscroll-behavior-y": {
      syntax: "contain | none | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overscroll Behavior"
      ],
      initial: "auto",
      appliesto: "nonReplacedBlockAndInlineBlockElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overscroll-behavior-y"
    },
    padding: {
      syntax: "<'padding-top'>{1,4}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: [
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top"
      ],
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: [
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top"
      ],
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding"
    },
    "padding-block": {
      syntax: "<'padding-top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "padding-block-start",
        "padding-block-end"
      ],
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: [
        "padding-block-start",
        "padding-block-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-block"
    },
    "padding-block-end": {
      syntax: "<'padding-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "asLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-block-end"
    },
    "padding-block-start": {
      syntax: "<'padding-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "asLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-block-start"
    },
    "padding-bottom": {
      syntax: "<length-percentage [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-bottom"
    },
    "padding-inline": {
      syntax: "<'padding-top'>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: [
        "padding-inline-start",
        "padding-inline-end"
      ],
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: [
        "padding-inline-start",
        "padding-inline-end"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-inline"
    },
    "padding-inline-end": {
      syntax: "<'padding-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "asLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-inline-end"
    },
    "padding-inline-start": {
      syntax: "<'padding-top'>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "logicalWidthOfContainingBlock",
      groups: [
        "CSS Logical Properties and Values"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "asLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-inline-start"
    },
    "padding-left": {
      syntax: "<length-percentage [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-left"
    },
    "padding-right": {
      syntax: "<length-percentage [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-right"
    },
    "padding-top": {
      syntax: "<length-percentage [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Model"
      ],
      initial: "0",
      appliesto: "allElementsExceptInternalTableDisplayTypes",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/padding-top"
    },
    page: {
      syntax: "auto | <custom-ident>",
      media: "paged",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Paged Media"
      ],
      initial: "auto",
      appliesto: "blockElementsInNormalFlow",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/page"
    },
    "page-break-after": {
      syntax: "auto | always | avoid | left | right | recto | verso",
      media: [
        "visual",
        "paged"
      ],
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Paged Media"
      ],
      initial: "auto",
      appliesto: "blockElementsInNormalFlow",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/page-break-after"
    },
    "page-break-before": {
      syntax: "auto | always | avoid | left | right | recto | verso",
      media: [
        "visual",
        "paged"
      ],
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Paged Media"
      ],
      initial: "auto",
      appliesto: "blockElementsInNormalFlow",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/page-break-before"
    },
    "page-break-inside": {
      syntax: "auto | avoid",
      media: [
        "visual",
        "paged"
      ],
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Paged Media"
      ],
      initial: "auto",
      appliesto: "blockElementsInNormalFlow",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/page-break-inside"
    },
    "paint-order": {
      syntax: "normal | [ fill || stroke || markers ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "normal",
      appliesto: "textElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/paint-order"
    },
    perspective: {
      syntax: "none | <length>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "absoluteLengthOrNone",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/perspective"
    },
    "perspective-origin": {
      syntax: "<position>",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpc",
      percentages: "referToSizeOfBoundingBox",
      groups: [
        "CSS Transforms"
      ],
      initial: "50% 50%",
      appliesto: "transformableElements",
      computed: "forLengthAbsoluteValueOtherwisePercentage",
      order: "oneOrTwoValuesLengthAbsoluteKeywordsPercentages",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/perspective-origin"
    },
    "place-content": {
      syntax: "<'align-content'> <'justify-content'>?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: [
        "align-content",
        "justify-content"
      ],
      appliesto: "multilineFlexContainers",
      computed: [
        "align-content",
        "justify-content"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/place-content"
    },
    "place-items": {
      syntax: "<'align-items'> <'justify-items'>?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: [
        "align-items",
        "justify-items"
      ],
      appliesto: "allElements",
      computed: [
        "align-items",
        "justify-items"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/place-items"
    },
    "place-self": {
      syntax: "<'align-self'> <'justify-self'>?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Box Alignment"
      ],
      initial: [
        "align-self",
        "justify-self"
      ],
      appliesto: "blockLevelBoxesAndAbsolutelyPositionedBoxesAndGridItems",
      computed: [
        "align-self",
        "justify-self"
      ],
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/place-self"
    },
    "pointer-events": {
      syntax: "auto | none | visiblePainted | visibleFill | visibleStroke | visible | painted | fill | stroke | all | inherit",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/pointer-events"
    },
    position: {
      syntax: "static | relative | absolute | sticky | fixed",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Positioned Layout"
      ],
      initial: "static",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position"
    },
    "position-anchor": {
      syntax: "auto | none | <anchor-name>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "none",
      appliesto: "absolutelyPositionedElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-anchor"
    },
    "position-area": {
      syntax: "none | <position-area>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "none",
      appliesto: "positionedElementsWithADefaultAnchorElement",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-area"
    },
    "position-try": {
      syntax: "<'position-try-order'>? <'position-try-fallbacks'>",
      media: "visual",
      inherited: false,
      animationType: [
        "position-try-fallbacks",
        "position-try-order"
      ],
      percentages: [
        "position-try-fallbacks",
        "position-try-order"
      ],
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: [
        "position-try-fallbacks",
        "position-try-order"
      ],
      appliesto: "absolutelyPositionedElements",
      computed: [
        "position-try-fallbacks",
        "position-try-order"
      ],
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-try"
    },
    "position-try-fallbacks": {
      syntax: "none | [ [<dashed-ident> || <try-tactic>] | <'position-area'> ]#",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "none",
      appliesto: "absolutelyPositionedElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-try-fallbacks"
    },
    "position-try-order": {
      syntax: "normal | <try-size>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "normal",
      appliesto: "absolutelyPositionedElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-try-order"
    },
    "position-visibility": {
      syntax: "always | [ anchors-valid || anchors-visible || no-overflow ]",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Anchor Positioning"
      ],
      initial: "anchors-visible",
      appliesto: "absolutelyPositionedElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/position-visibility"
    },
    "print-color-adjust": {
      syntax: "economy | exact",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Color"
      ],
      initial: "economy",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/print-color-adjust"
    },
    quotes: {
      syntax: "none | auto | [ <string> <string> ]+",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Generated Content"
      ],
      initial: "dependsOnUserAgent",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/quotes"
    },
    r: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportSize",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsCircle",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/r"
    },
    "reading-flow": {
      syntax: "normal | source-order | flex-visual | flex-flow | grid-rows | grid-columns | grid-order",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Display"
      ],
      initial: "normal",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/reading-flow"
    },
    "reading-order": {
      syntax: "<integer>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Display"
      ],
      initial: "0",
      appliesto: "blockContainersFlexContainersGridContainers",
      computed: "specifiedInteger",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/reading-order"
    },
    resize: {
      syntax: "none | both | horizontal | vertical | block | inline",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "none",
      appliesto: "elementsWithOverflowNotVisibleAndReplacedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/resize"
    },
    right: {
      syntax: "auto | <length-percentage> | <anchor()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Anchor Positioning",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/right"
    },
    rotate: {
      syntax: "none | <angle> | [ x | y | z | <number>{3} ] && <angle>",
      media: "visual",
      inherited: false,
      animationType: "transform",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/rotate"
    },
    "row-gap": {
      syntax: "normal | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToDimensionOfContentArea",
      groups: [
        "CSS Box Alignment"
      ],
      initial: "normal",
      appliesto: "multiColumnElementsFlexContainersGridContainers",
      computed: "asSpecifiedWithLengthsAbsoluteAndNormalComputingToZeroExceptMultiColumn",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/row-gap"
    },
    "ruby-align": {
      syntax: "start | center | space-between | space-around",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Ruby"
      ],
      initial: "space-around",
      appliesto: "rubyBasesAnnotationsBaseAnnotationContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/ruby-align"
    },
    "ruby-merge": {
      syntax: "separate | collapse | auto",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Ruby"
      ],
      initial: "separate",
      appliesto: "rubyAnnotationContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "experimental"
    },
    "ruby-overhang": {
      syntax: "auto | none",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Ruby"
      ],
      initial: "auto",
      appliesto: "rubyAnnotationContainers",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "standard"
    },
    "ruby-position": {
      syntax: "[ alternate || [ over | under ] ] | inter-character",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Ruby"
      ],
      initial: "alternate",
      appliesto: "rubyAnnotationContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/ruby-position"
    },
    rx: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportWidth",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsEllipseRect",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/rx"
    },
    ry: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportHeight",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsEllipseRect",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/ry"
    },
    scale: {
      syntax: "none | [ <number> | <percentage> ]{1,3}",
      media: "visual",
      inherited: false,
      animationType: "transform",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scale"
    },
    "scroll-behavior": {
      syntax: "auto | smooth",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "auto",
      appliesto: "scrollingBoxes",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-behavior"
    },
    "scroll-initial-target": {
      syntax: "none | nearest",
      media: "noPracticalMedia",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "experimental"
    },
    "scroll-margin": {
      syntax: "<length>{1,4}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-margin-bottom",
        "scroll-margin-left",
        "scroll-margin-right",
        "scroll-margin-top"
      ],
      appliesto: "allElements",
      computed: [
        "scroll-margin-bottom",
        "scroll-margin-left",
        "scroll-margin-right",
        "scroll-margin-top"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin"
    },
    "scroll-margin-block": {
      syntax: "<length>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-margin-block-start",
        "scroll-margin-block-end"
      ],
      appliesto: "allElements",
      computed: [
        "scroll-margin-block-start",
        "scroll-margin-block-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-block"
    },
    "scroll-margin-block-end": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-block-end"
    },
    "scroll-margin-block-start": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-block-start"
    },
    "scroll-margin-bottom": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-bottom"
    },
    "scroll-margin-inline": {
      syntax: "<length>{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-margin-inline-start",
        "scroll-margin-inline-end"
      ],
      appliesto: "allElements",
      computed: [
        "scroll-margin-inline-start",
        "scroll-margin-inline-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-inline"
    },
    "scroll-margin-inline-end": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-inline-end"
    },
    "scroll-margin-inline-start": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-inline-start"
    },
    "scroll-margin-left": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-left"
    },
    "scroll-margin-right": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-right"
    },
    "scroll-margin-top": {
      syntax: "<length>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-margin-top"
    },
    "scroll-marker-group": {
      syntax: "none | before | after",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-marker-group"
    },
    "scroll-padding": {
      syntax: "[ auto | <length-percentage> ]{1,4}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-padding-bottom",
        "scroll-padding-left",
        "scroll-padding-right",
        "scroll-padding-top"
      ],
      appliesto: "scrollContainers",
      computed: [
        "scroll-padding-bottom",
        "scroll-padding-left",
        "scroll-padding-right",
        "scroll-padding-top"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding"
    },
    "scroll-padding-block": {
      syntax: "[ auto | <length-percentage> ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-padding-block-start",
        "scroll-padding-block-end"
      ],
      appliesto: "scrollContainers",
      computed: [
        "scroll-padding-block-start",
        "scroll-padding-block-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-block"
    },
    "scroll-padding-block-end": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-block-end"
    },
    "scroll-padding-block-start": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-block-start"
    },
    "scroll-padding-bottom": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-bottom"
    },
    "scroll-padding-inline": {
      syntax: "[ auto | <length-percentage> ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: [
        "scroll-padding-inline-start",
        "scroll-padding-inline-end"
      ],
      appliesto: "scrollContainers",
      computed: [
        "scroll-padding-inline-start",
        "scroll-padding-inline-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-inline"
    },
    "scroll-padding-inline-end": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-inline-end"
    },
    "scroll-padding-inline-start": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-inline-start"
    },
    "scroll-padding-left": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-left"
    },
    "scroll-padding-right": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-right"
    },
    "scroll-padding-top": {
      syntax: "auto | <length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToTheScrollContainersScrollport",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "auto",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-padding-top"
    },
    "scroll-snap-align": {
      syntax: "[ none | start | end | center ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-snap-align"
    },
    "scroll-snap-coordinate": {
      syntax: "none | <position>#",
      media: "interactive",
      inherited: false,
      animationType: "position",
      percentages: "referToBorderBox",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-snap-destination": {
      syntax: "<position>",
      media: "interactive",
      inherited: false,
      animationType: "position",
      percentages: "relativeToScrollContainerPaddingBoxAxis",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "0px 0px",
      appliesto: "scrollContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-snap-points-x": {
      syntax: "none | repeat( <length-percentage> )",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "relativeToScrollContainerPaddingBoxAxis",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-snap-points-y": {
      syntax: "none | repeat( <length-percentage> )",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "relativeToScrollContainerPaddingBoxAxis",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-snap-stop": {
      syntax: "normal | always",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-snap-stop"
    },
    "scroll-snap-type": {
      syntax: "none | [ x | y | block | inline | both ] [ mandatory | proximity ]?",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-snap-type"
    },
    "scroll-snap-type-x": {
      syntax: "none | mandatory | proximity",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-snap-type-y": {
      syntax: "none | mandatory | proximity",
      media: "interactive",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scroll Snap"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "obsolete"
    },
    "scroll-target-group": {
      syntax: "none | auto",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-target-group"
    },
    "scroll-timeline": {
      syntax: "[ <'scroll-timeline-name'> <'scroll-timeline-axis'>? ]#",
      media: "visual",
      inherited: false,
      animationType: [
        "scroll-timeline-name",
        "scroll-timeline-axis"
      ],
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: [
        "scroll-timeline-name",
        "scroll-timeline-axis"
      ],
      appliesto: "scrollContainers",
      computed: [
        "scroll-timeline-name",
        "scroll-timeline-axis"
      ],
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-timeline"
    },
    "scroll-timeline-axis": {
      syntax: "[ block | inline | x | y ]#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "block",
      appliesto: "scrollContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-timeline-axis"
    },
    "scroll-timeline-name": {
      syntax: "[ none | <dashed-ident> ]#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "none",
      appliesto: "scrollContainers",
      computed: "noneOrOrderedListOfIdentifiers",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scroll-timeline-name"
    },
    "scrollbar-color": {
      syntax: "auto | <color>{2}",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Scrollbars Styling"
      ],
      initial: "auto",
      appliesto: "scrollingBoxes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scrollbar-color"
    },
    "scrollbar-gutter": {
      syntax: "auto | stable && both-edges?",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "auto",
      appliesto: "scrollingBoxes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scrollbar-gutter"
    },
    "scrollbar-width": {
      syntax: "auto | thin | none",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Scrollbars Styling"
      ],
      initial: "auto",
      appliesto: "scrollingBoxes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/scrollbar-width"
    },
    "shape-image-threshold": {
      syntax: "<opacity-value>",
      media: "visual",
      inherited: false,
      animationType: "number",
      percentages: "no",
      groups: [
        "CSS Shapes"
      ],
      initial: "0.0",
      appliesto: "floats",
      computed: "specifiedValueNumberClipped0To1",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/shape-image-threshold"
    },
    "shape-margin": {
      syntax: "<length-percentage>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Shapes"
      ],
      initial: "0",
      appliesto: "floats",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/shape-margin"
    },
    "shape-outside": {
      syntax: "none | [ <shape-box> || <basic-shape> ] | <image>",
      media: "visual",
      inherited: false,
      animationType: "basicShapeOtherwiseNo",
      percentages: "no",
      groups: [
        "CSS Shapes"
      ],
      initial: "none",
      appliesto: "floats",
      computed: "asDefinedForBasicShapeWithAbsoluteURIOtherwiseAsSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/shape-outside"
    },
    "shape-rendering": {
      syntax: "auto | optimizeSpeed | crispEdges | geometricPrecision",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "auto",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/shape-rendering"
    },
    "speak-as": {
      syntax: "normal | spell-out || digits || [ literal-punctuation | no-punctuation ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Speech"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "specifiedValue",
      order: "perGrammar",
      status: "experimental"
    },
    "stop-color": {
      syntax: "<'color'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "black",
      appliesto: "limitedSVGElementsStop",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stop-color"
    },
    "stop-opacity": {
      syntax: "<'opacity'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "black",
      appliesto: "limitedSVGElementsStop",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stop-opacity"
    },
    stroke: {
      syntax: "<paint>",
      media: "visual",
      inherited: true,
      animationType: [
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width"
      ],
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: [
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-opacity",
        "stroke-width"
      ],
      appliesto: "asLonghands",
      computed: "asLonghands",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke"
    },
    "stroke-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "transparent",
      appliesto: "textAndSVGShapes",
      computed: "computedColor",
      order: "perGrammar",
      status: "experimental"
    },
    "stroke-dasharray": {
      syntax: "none | <dasharray>",
      media: "visual",
      inherited: true,
      animationType: "repeatableList",
      percentages: "referToSVGViewportDiagonal",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsShapes",
      computed: "listEachItemConsistingOfAbsoluteLengthPercentageOrKeyword",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-dasharray"
    },
    "stroke-dashoffset": {
      syntax: "<length-percentage> | <number>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportDiagonal",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsShapes",
      computed: "absoluteLengthOrPercentageNumbersConverted",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-dashoffset"
    },
    "stroke-linecap": {
      syntax: "butt | round | square",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "butt",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-linecap"
    },
    "stroke-linejoin": {
      syntax: "miter | miter-clip | round | bevel | arcs",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "miter",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-linejoin"
    },
    "stroke-miterlimit": {
      syntax: "<number>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "4",
      appliesto: "limitedSVGElementsShapes",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-miterlimit"
    },
    "stroke-opacity": {
      syntax: "<'opacity'>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "1",
      appliesto: "limitedSVGElementsShapes",
      computed: "specifiedValueClipped0To1",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-opacity"
    },
    "stroke-width": {
      syntax: "<length-percentage> | <number>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportDiagonal",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "1px",
      appliesto: "limitedSVGElementsShapes",
      computed: "absoluteLengthOrPercentageNumbersConverted",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/stroke-width"
    },
    "tab-size": {
      syntax: "<integer> | <length>",
      media: "visual",
      inherited: true,
      animationType: "length",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "8",
      appliesto: "blockContainers",
      computed: "specifiedIntegerOrAbsoluteLength",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/tab-size"
    },
    "table-layout": {
      syntax: "auto | fixed",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Table"
      ],
      initial: "auto",
      appliesto: "tableElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/table-layout"
    },
    "text-align": {
      syntax: "start | end | left | right | center | justify | match-parent",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "startOrNamelessValueIfLTRRightIfRTL",
      appliesto: "blockContainers",
      computed: "asSpecifiedExceptMatchParent",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-align"
    },
    "text-align-last": {
      syntax: "auto | start | end | left | right | center | justify",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "blockContainers",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-align-last"
    },
    "text-anchor": {
      syntax: "start | middle | end",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "start",
      appliesto: "limitedSVGElementsTextContent",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-anchor"
    },
    "text-autospace": {
      syntax: "normal | <autospace> | auto",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "textElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-autospace"
    },
    "text-box": {
      syntax: "normal | <'text-box-trim'> || <'text-box-edge'>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "normal",
      appliesto: "blockContainersAndInlineBoxes",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "standard"
    },
    "text-box-edge": {
      syntax: "auto | <text-edge>",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "auto",
      appliesto: "blockContainersAndInlineBoxes",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "standard"
    },
    "text-box-trim": {
      syntax: "none | trim-start | trim-end | trim-both",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Inline"
      ],
      initial: "none",
      appliesto: "blockContainersAndInlineBoxes",
      computed: "theSpecifiedKeyword",
      order: "perGrammar",
      status: "standard"
    },
    "text-combine-upright": {
      syntax: "none | all | [ digits <integer>? ]",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Writing Modes"
      ],
      initial: "none",
      appliesto: "nonReplacedInlineElements",
      computed: "keywordPlusIntegerIfDigits",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-combine-upright"
    },
    "text-decoration": {
      syntax: "<'text-decoration-line'> || <'text-decoration-style'> || <'text-decoration-color'> || <'text-decoration-thickness'>",
      media: "visual",
      inherited: false,
      animationType: [
        "text-decoration-color",
        "text-decoration-style",
        "text-decoration-line",
        "text-decoration-thickness"
      ],
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: [
        "text-decoration-color",
        "text-decoration-style",
        "text-decoration-line"
      ],
      appliesto: "allElements",
      computed: [
        "text-decoration-line",
        "text-decoration-style",
        "text-decoration-color",
        "text-decoration-thickness"
      ],
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration"
    },
    "text-decoration-color": {
      syntax: "<color>",
      media: "visual",
      inherited: false,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-color"
    },
    "text-decoration-inset": {
      syntax: "<length>{1,2} | auto",
      media: "visual",
      inherited: false,
      animationType: "byComputedValue",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "0",
      appliesto: "allElements",
      computed: "absoluteLengthOrKeyword",
      order: "perGrammar",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-inset"
    },
    "text-decoration-line": {
      syntax: "none | [ underline || overline || line-through || blink ] | spelling-error | grammar-error",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-line"
    },
    "text-decoration-skip": {
      syntax: "none | [ objects || [ spaces | [ leading-spaces || trailing-spaces ] ] || edges || box-decoration ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "objects",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-skip"
    },
    "text-decoration-skip-ink": {
      syntax: "auto | all | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-skip-ink"
    },
    "text-decoration-style": {
      syntax: "solid | double | dotted | dashed | wavy",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "solid",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-style"
    },
    "text-decoration-thickness": {
      syntax: "auto | from-font | <length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToElementFontSize",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-decoration-thickness"
    },
    "text-emphasis": {
      syntax: "<'text-emphasis-style'> || <'text-emphasis-color'>",
      media: "visual",
      inherited: true,
      animationType: [
        "text-emphasis-color",
        "text-emphasis-style"
      ],
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: [
        "text-emphasis-style",
        "text-emphasis-color"
      ],
      appliesto: "allElements",
      computed: [
        "text-emphasis-style",
        "text-emphasis-color"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-emphasis"
    },
    "text-emphasis-color": {
      syntax: "<color>",
      media: "visual",
      inherited: true,
      animationType: "color",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "currentcolor",
      appliesto: "allElements",
      computed: "computedColor",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-emphasis-color"
    },
    "text-emphasis-position": {
      syntax: "auto | [ over | under ] && [ right | left ]?",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-emphasis-position"
    },
    "text-emphasis-style": {
      syntax: "none | [ [ filled | open ] || [ dot | circle | double-circle | triangle | sesame ] ] | <string>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-emphasis-style"
    },
    "text-indent": {
      syntax: "<length-percentage> && hanging? && each-line?",
      media: "visual",
      inherited: true,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Text"
      ],
      initial: "0",
      appliesto: "blockContainers",
      computed: "percentageOrAbsoluteLengthPlusKeywords",
      order: "lengthOrPercentageBeforeKeywords",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-indent"
    },
    "text-justify": {
      syntax: "auto | inter-character | inter-word | none",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "inlineLevelAndTableCellElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-justify"
    },
    "text-orientation": {
      syntax: "mixed | upright | sideways",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Writing Modes"
      ],
      initial: "mixed",
      appliesto: "allElementsExceptTableRowGroupsRowsColumnGroupsAndColumns",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-orientation"
    },
    "text-overflow": {
      syntax: "[ clip | ellipsis | <string> ]{1,2}",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Overflow"
      ],
      initial: "clip",
      appliesto: "blockContainerElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-overflow"
    },
    "text-rendering": {
      syntax: "auto | optimizeSpeed | optimizeLegibility | geometricPrecision",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "auto",
      appliesto: "textElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-rendering"
    },
    "text-shadow": {
      syntax: "none | <shadow-t>#",
      media: "visual",
      inherited: true,
      animationType: "shadowList",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "colorPlusThreeAbsoluteLengths",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-shadow"
    },
    "text-size-adjust": {
      syntax: "none | auto | <percentage>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "referToSizeOfFont",
      groups: [
        "CSS Mobile Text Size Adjustment"
      ],
      initial: "autoForSmartphoneBrowsersSupportingInflation",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-size-adjust"
    },
    "text-spacing-trim": {
      syntax: "space-all | normal | space-first | trim-start",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "textElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-spacing-trim"
    },
    "text-transform": {
      syntax: "none | [ capitalize | uppercase | lowercase ] || full-width || full-size-kana | math-auto",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text",
        "MathML"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-transform"
    },
    "text-underline-offset": {
      syntax: "auto | <length> | <percentage>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "referToElementFontSize",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-underline-offset"
    },
    "text-underline-position": {
      syntax: "auto | from-font | [ under || [ left | right ] ]",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text Decoration"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-underline-position"
    },
    "text-wrap": {
      syntax: "<'text-wrap-mode'> || <'text-wrap-style'>",
      media: "visual",
      inherited: true,
      animationType: [
        "text-wrap-mode",
        "text-wrap-style"
      ],
      percentages: [
        "text-wrap-mode",
        "text-wrap-style"
      ],
      groups: [
        "CSS Text"
      ],
      initial: "wrap",
      appliesto: "textAndBlockContainers",
      computed: [
        "text-wrap-mode",
        "text-wrap-style"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-wrap"
    },
    "text-wrap-mode": {
      syntax: "wrap | nowrap",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "wrap",
      appliesto: "textAndBlockContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-wrap-mode"
    },
    "text-wrap-style": {
      syntax: "auto | balance | stable | pretty",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "auto",
      appliesto: "textAndBlockContainers",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/text-wrap-style"
    },
    "timeline-scope": {
      syntax: "none | <dashed-ident>#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "noneOrOrderedListOfIdentifiers",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/timeline-scope"
    },
    "timeline-trigger": {
      syntax: "none | [ <'timeline-trigger-name'> <'timeline-trigger-source'> <'timeline-trigger-range'> [ '/' <'timeline-trigger-exit-range'> ]? ]#",
      media: "visual",
      inherited: false,
      animationType: [
        "timeline-trigger-name",
        "timeline-trigger-source",
        "timeline-trigger-range",
        "timeline-trigger-exit-range"
      ],
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: [
        "timeline-trigger-name",
        "timeline-trigger-source",
        "timeline-trigger-range",
        "timeline-trigger-exit-range"
      ],
      appliesto: "allElements",
      computed: [
        "timeline-trigger-name",
        "timeline-trigger-source",
        "timeline-trigger-range",
        "timeline-trigger-exit-range"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger"
    },
    "timeline-trigger-name": {
      syntax: "none | <dashed-ident>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-name"
    },
    "timeline-trigger-exit-range": {
      syntax: "[ <'timeline-trigger-exit-range-start'> <'timeline-trigger-exit-range-end'>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: [
        "timeline-trigger-exit-range-start",
        "timeline-trigger-exit-range-end"
      ],
      groups: [
        "CSS Animations"
      ],
      initial: [
        "timeline-trigger-exit-range-start",
        "timeline-trigger-exit-range-end"
      ],
      appliesto: "allElements",
      computed: [
        "timeline-trigger-exit-range-start",
        "timeline-trigger-exit-range-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-exit-range"
    },
    "timeline-trigger-exit-range-end": {
      syntax: "[ auto | normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "CSS Animations"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-exit-range-end"
    },
    "timeline-trigger-exit-range-start": {
      syntax: "[ auto | normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "CSS Animations"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-exit-range-start"
    },
    "timeline-trigger-range": {
      syntax: "[ <'timeline-trigger-range-start'> <'timeline-trigger-range-end'>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: [
        "timeline-trigger-range-start",
        "timeline-trigger-range-end"
      ],
      groups: [
        "CSS Animations"
      ],
      initial: [
        "timeline-trigger-range-start",
        "timeline-trigger-range-end"
      ],
      appliesto: "allElements",
      computed: [
        "timeline-trigger-range-start",
        "timeline-trigger-range-end"
      ],
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-range"
    },
    "timeline-trigger-range-end": {
      syntax: "[ normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "CSS Animations"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-range-end"
    },
    "timeline-trigger-range-start": {
      syntax: "[ normal | <length-percentage> | <timeline-range-name> <length-percentage>? ]#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "relativeToTimelineRangeIfSpecifiedOtherwiseEntireTimeline",
      groups: [
        "CSS Animations"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfNormalLengthPercentageOrNameLengthPercentage",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-range-start"
    },
    "timeline-trigger-source": {
      syntax: "<single-animation-timeline>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "listOfNoneAutoIdentScrollOrView",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/timeline-trigger-source"
    },
    top: {
      syntax: "auto | <length-percentage> | <anchor()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToContainingBlockHeight",
      groups: [
        "CSS Anchor Positioning",
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "lengthAbsolutePercentageAsSpecifiedOtherwiseAuto",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/top"
    },
    "touch-action": {
      syntax: "auto | none | [ [ pan-x | pan-left | pan-right ] || [ pan-y | pan-up | pan-down ] || pinch-zoom ] | manipulation",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Pointer Events"
      ],
      initial: "auto",
      appliesto: "allElementsExceptNonReplacedInlineElementsTableRowsColumnsRowColumnGroups",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/touch-action"
    },
    transform: {
      syntax: "none | <transform-list>",
      media: "visual",
      inherited: false,
      animationType: "transform",
      percentages: "referToSizeOfBoundingBox",
      groups: [
        "CSS Transforms"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transform"
    },
    "transform-box": {
      syntax: "content-box | border-box | fill-box | stroke-box | view-box",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "view-box",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transform-box"
    },
    "transform-origin": {
      syntax: "[ <length-percentage> | left | center | right | top | bottom ] | [ [ <length-percentage> | left | center | right ] && [ <length-percentage> | top | center | bottom ] ] <length>?",
      media: "visual",
      inherited: false,
      animationType: "simpleListOfLpc",
      percentages: "referToSizeOfBoundingBox",
      groups: [
        "CSS Transforms"
      ],
      initial: "50% 50% 0",
      appliesto: "transformableElements",
      computed: "forLengthAbsoluteValueOtherwisePercentage",
      order: "oneOrTwoValuesLengthAbsoluteKeywordsPercentages",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transform-origin"
    },
    "transform-style": {
      syntax: "flat | preserve-3d",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Transforms"
      ],
      initial: "flat",
      appliesto: "transformableElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transform-style"
    },
    transition: {
      syntax: "<single-transition>#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: [
        "transition-delay",
        "transition-duration",
        "transition-property",
        "transition-timing-function",
        "transition-behavior"
      ],
      appliesto: "allElementsAndPseudos",
      computed: [
        "transition-delay",
        "transition-duration",
        "transition-property",
        "transition-timing-function",
        "transition-behavior"
      ],
      order: "orderOfAppearance",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition"
    },
    "transition-behavior": {
      syntax: "<transition-behavior-value>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition-behavior"
    },
    "transition-delay": {
      syntax: "<time>#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: "0s",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition-delay"
    },
    "transition-duration": {
      syntax: "<time>#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: "0s",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition-duration"
    },
    "transition-property": {
      syntax: "none | <single-transition-property>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: "all",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition-property"
    },
    "transition-timing-function": {
      syntax: "<easing-function>#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Transitions"
      ],
      initial: "ease",
      appliesto: "allElementsAndPseudos",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/transition-timing-function"
    },
    translate: {
      syntax: "none | <length-percentage> [ <length-percentage> <length>? ]?",
      media: "visual",
      inherited: false,
      animationType: "transform",
      percentages: "referToSizeOfBoundingBox",
      groups: [
        "CSS Transforms"
      ],
      initial: "none",
      appliesto: "transformableElements",
      computed: "asSpecifiedRelativeToAbsoluteLengths",
      order: "perGrammar",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/translate"
    },
    "trigger-scope": {
      syntax: "none | all | <dashed-ident>#",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Animations"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/Reference/Properties/trigger-scope"
    },
    "unicode-bidi": {
      syntax: "normal | embed | isolate | bidi-override | isolate-override | plaintext",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Writing Modes"
      ],
      initial: "normal",
      appliesto: "allElementsSomeValuesNoEffectOnNonInlineElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/unicode-bidi"
    },
    "user-select": {
      syntax: "auto | text | none | all",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Basic User Interface"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/user-select"
    },
    "vector-effect": {
      syntax: "none | non-scaling-stroke | non-scaling-size | non-rotation | fixed-position",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "none",
      appliesto: "limitedSVGElementsGraphicsAndUse",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/vector-effect"
    },
    "vertical-align": {
      syntax: "baseline | sub | super | text-top | text-bottom | middle | top | bottom | <percentage> | <length>",
      media: "visual",
      inherited: false,
      animationType: "length",
      percentages: "referToLineHeight",
      groups: [
        "CSS Inline"
      ],
      initial: "baseline",
      appliesto: "inlineLevelAndTableCellElements",
      computed: "absoluteLengthOrKeyword",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/vertical-align"
    },
    "view-timeline": {
      syntax: "[ <'view-timeline-name'> [ <'view-timeline-axis'> || <'view-timeline-inset'> ]? ]#",
      media: "visual",
      inherited: false,
      animationType: [
        "view-timeline-name",
        "view-timeline-axis"
      ],
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: [
        "view-timeline-name",
        "view-timeline-axis"
      ],
      appliesto: "allElements",
      computed: [
        "view-timeline-name",
        "view-timeline-axis"
      ],
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/view-timeline"
    },
    "view-timeline-axis": {
      syntax: "[ block | inline | x | y ]#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "block",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/view-timeline-axis"
    },
    "view-timeline-inset": {
      syntax: "[ [ auto | <length-percentage> ]{1,2} ]#",
      media: "interactive",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "relativeToCorrespondingDimensionOfRelevantScrollport",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "listEachItemConsistingOfPairsOfAutoOrLengthPercentage",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/view-timeline-inset"
    },
    "view-timeline-name": {
      syntax: "[ none | <dashed-ident> ]#",
      media: "interactive",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "Scroll-driven Animations"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "noneOrOrderedListOfIdentifiers",
      order: "perGrammar",
      status: "experimental",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/view-timeline-name"
    },
    "view-transition-class": {
      syntax: "none | <custom-ident>+",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS View Transitions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard"
    },
    "view-transition-name": {
      syntax: "none | <custom-ident> | match-element",
      media: "visual",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS View Transitions"
      ],
      initial: "none",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/view-transition-name"
    },
    visibility: {
      syntax: "visible | hidden | collapse",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Display",
        "Scalable Vector Graphics"
      ],
      initial: "visible",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/visibility"
    },
    "white-space": {
      syntax: "normal | pre | pre-wrap | pre-line | <'white-space-collapse'> || <'text-wrap-mode'>",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/white-space"
    },
    "white-space-collapse": {
      syntax: "collapse | preserve | preserve-breaks | preserve-spaces | break-spaces",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "collapse",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/white-space-collapse"
    },
    widows: {
      syntax: "<integer>",
      media: "visual",
      inherited: true,
      animationType: "byComputedValueType",
      percentages: "no",
      groups: [
        "CSS Fragmentation"
      ],
      initial: "2",
      appliesto: "blockContainerElements",
      computed: "asSpecified",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/widows"
    },
    width: {
      syntax: "auto | <length-percentage [0,∞]> | min-content | max-content | fit-content | fit-content(<length-percentage [0,∞]>) | <calc-size()> | <anchor-size()>",
      media: "visual",
      inherited: false,
      animationType: "lpc",
      percentages: "referToWidthOfContainingBlock",
      groups: [
        "CSS Box Sizing"
      ],
      initial: "auto",
      appliesto: "allElementsButNonReplacedAndTableRows",
      computed: "percentageAutoOrAbsoluteLength",
      order: "lengthOrPercentageBeforeKeywordIfBothPresent",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/width"
    },
    "will-change": {
      syntax: "auto | <animateable-feature>#",
      media: "all",
      inherited: false,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Will Change"
      ],
      initial: "auto",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/will-change"
    },
    "word-break": {
      syntax: "normal | break-all | keep-all | break-word | auto-phrase",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/word-break"
    },
    "word-spacing": {
      syntax: "normal | <length>",
      media: "visual",
      inherited: true,
      animationType: "length",
      percentages: "referToWidthOfAffectedGlyph",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "allElements",
      computed: "absoluteLength",
      order: "uniqueOrder",
      alsoAppliesTo: [
        "::first-letter",
        "::first-line",
        "::placeholder"
      ],
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/word-spacing"
    },
    "word-wrap": {
      syntax: "normal | break-word",
      media: "visual",
      inherited: true,
      animationType: "discrete",
      percentages: "no",
      groups: [
        "CSS Text"
      ],
      initial: "normal",
      appliesto: "nonReplacedInlineElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/overflow-wrap"
    },
    "writing-mode": {
      syntax: "horizontal-tb | vertical-rl | vertical-lr | sideways-rl | sideways-lr",
      media: "visual",
      inherited: true,
      animationType: "notAnimatable",
      percentages: "no",
      groups: [
        "CSS Writing Modes"
      ],
      initial: "horizontal-tb",
      appliesto: "allElementsExceptTableRowColumnGroupsTableRowsColumns",
      computed: "asSpecified",
      order: "uniqueOrder",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/writing-mode"
    },
    x: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportWidth",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsGeometry",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/x"
    },
    y: {
      syntax: "<length> | <percentage>",
      media: "visual",
      inherited: false,
      animationType: "byComputedValueType",
      percentages: "referToSVGViewportHeight",
      groups: [
        "Scalable Vector Graphics"
      ],
      initial: "0",
      appliesto: "limitedSVGElementsGeometry",
      computed: "percentageAsSpecifiedOrAbsoluteLength",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/y"
    },
    "z-index": {
      syntax: "auto | <integer>",
      media: "visual",
      inherited: false,
      animationType: "integer",
      percentages: "no",
      groups: [
        "CSS Positioned Layout"
      ],
      initial: "auto",
      appliesto: "positionedElements",
      computed: "asSpecified",
      order: "uniqueOrder",
      stacking: true,
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/z-index"
    },
    zoom: {
      syntax: "normal | reset | <number [0,∞]> || <percentage [0,∞]>",
      media: "visual",
      inherited: false,
      animationType: "notAnimatable",
      percentages: "convertedToNumber",
      groups: [
        "CSS Viewport"
      ],
      initial: "1",
      appliesto: "allElements",
      computed: "asSpecifiedButWithPercentageConvertedToTheEquivalentNumber",
      order: "perGrammar",
      status: "standard",
      mdn_url: "https://developer.mozilla.org/docs/Web/CSS/zoom"
    }
  };
});

// ../imp-pinned/node_modules/mdn-data/css/syntaxes.json
var require_syntaxes = __commonJS((exports, module) => {
  module.exports = {
    "abs()": {
      syntax: "abs( <calc-sum> )"
    },
    "absolute-size": {
      syntax: "xx-small | x-small | small | medium | large | x-large | xx-large | xxx-large"
    },
    "acos()": {
      syntax: "acos( <calc-sum> )"
    },
    "alpha-value": {
      syntax: "<number> | <percentage>"
    },
    "an+b": {
      syntax: "odd | even | <integer> | <n-dimension> | '+'?† n | -n | <ndashdigit-dimension> | '+'?† <ndashdigit-ident> | <dashndashdigit-ident> | <n-dimension> <signed-integer> | '+'?† n <signed-integer> | -n <signed-integer> | <ndash-dimension> <signless-integer> | '+'?† n- <signless-integer> | -n- <signless-integer> | <n-dimension> ['+' | '-'] <signless-integer> | '+'?† n ['+' | '-'] <signless-integer> | -n ['+' | '-'] <signless-integer>"
    },
    "anchor()": {
      syntax: "anchor( <anchor-name>? && <anchor-side>, <length-percentage>? )"
    },
    "anchor-name": {
      syntax: "<dashed-ident>"
    },
    "anchor-side": {
      syntax: "inside | outside | top | left | right | bottom | start | end | self-start | self-end | <percentage> | center"
    },
    "anchor-size": {
      syntax: "width | height | block | inline | self-block | self-inline"
    },
    "anchor-size()": {
      syntax: "anchor-size( [ <anchor-name> || <anchor-size> ]? , <length-percentage>? )"
    },
    "angle-percentage": {
      syntax: "<angle> | <percentage>"
    },
    "angular-color-hint": {
      syntax: "<angle-percentage> | <zero>"
    },
    "angular-color-stop": {
      syntax: "<color> <color-stop-angle>?"
    },
    "angular-color-stop-list": {
      syntax: "<angular-color-stop> , [ <angular-color-hint>? , <angular-color-stop> ]#?"
    },
    "animateable-feature": {
      syntax: "scroll-position | contents | <custom-ident>"
    },
    "animation-action": {
      syntax: "none | play | play-once | play-forwards | play-backwards | pause | reset | replay"
    },
    "asin()": {
      syntax: "asin( <calc-sum> )"
    },
    "atan()": {
      syntax: "atan( <calc-sum> )"
    },
    "atan2()": {
      syntax: "atan2( <calc-sum>, <calc-sum> )"
    },
    attachment: {
      syntax: "scroll | fixed | local"
    },
    "attr()": {
      syntax: "attr( <attr-name> <attr-type>? , <declaration-value>? )"
    },
    "attr-matcher": {
      syntax: "[ '~' | '|' | '^' | '$' | '*' ]? '='"
    },
    "attr-modifier": {
      syntax: "i | s"
    },
    "attr-type": {
      syntax: "type( <syntax> ) | raw-string | number | <attr-unit>"
    },
    "attribute-selector": {
      syntax: "'[' <wq-name> ']' | '[' <wq-name> <attr-matcher> [ <string-token> | <ident-token> ] <attr-modifier>? ']'"
    },
    "auto-repeat": {
      syntax: "repeat( [ auto-fill | auto-fit ] , [ <line-names>? <fixed-size> ]+ <line-names>? )"
    },
    "auto-track-list": {
      syntax: `[ <line-names>? [ <fixed-size> | <fixed-repeat> ] ]* <line-names>? <auto-repeat>
[ <line-names>? [ <fixed-size> | <fixed-repeat> ] ]* <line-names>?`
    },
    axis: {
      syntax: "block | inline | x | y"
    },
    "baseline-position": {
      syntax: "[ first | last ]? baseline"
    },
    "basic-shape": {
      syntax: "<inset()> | <xywh()> | <rect()> | <circle()> | <ellipse()> | <polygon()> | <path()>"
    },
    "basic-shape-rect": {
      syntax: "<inset()> | <rect()> | <xywh()>"
    },
    "bg-clip": {
      syntax: "<visual-box> | border-area | text"
    },
    "bg-image": {
      syntax: "<image> | none"
    },
    "bg-layer": {
      syntax: "<bg-image> || <bg-position> [ / <bg-size> ]? || <repeat-style> || <attachment> || <visual-box> || <visual-box>"
    },
    "bg-position": {
      syntax: "[ [ left | center | right | top | bottom | <length-percentage> ] | [ left | center | right | <length-percentage> ] [ top | center | bottom | <length-percentage> ] | [ center | [ left | right ] <length-percentage>? ] && [ center | [ top | bottom ] <length-percentage>? ] ]"
    },
    "bg-size": {
      syntax: "[ <length-percentage [0,∞]> | auto ]{1,2} | cover | contain"
    },
    "blend-mode": {
      syntax: "normal | multiply | screen | overlay | darken | lighten | color-dodge | color-burn | hard-light | soft-light | difference | exclusion | hue | saturation | color | luminosity"
    },
    "blur()": {
      syntax: "blur( <length>? )"
    },
    "brightness()": {
      syntax: "brightness( [ <number> | <percentage> ]? )"
    },
    "calc()": {
      syntax: "calc( <calc-sum> )"
    },
    "calc-constant": {
      syntax: "e | pi | infinity | -infinity | NaN"
    },
    "calc-product": {
      syntax: "<calc-value> [ '*' <calc-value> | '/' <number> ]*"
    },
    "calc-size()": {
      syntax: "calc-size( <calc-size-basis>, <calc-sum> )"
    },
    "calc-size-basis": {
      syntax: "<intrinsic-size-keyword> | <calc-size()> | any | <calc-sum>"
    },
    "calc-sum": {
      syntax: "<calc-product> [ [ '+' | '-' ] <calc-product> ]*"
    },
    "calc-value": {
      syntax: "<number> | <dimension> | <percentage> | <calc-constant> | ( <calc-sum> )"
    },
    "cf-final-image": {
      syntax: "<image> | <color>"
    },
    "cf-mixing-image": {
      syntax: "<percentage>? && <image>"
    },
    "circle()": {
      syntax: "circle( <radial-size>? [ at <position> ]? )"
    },
    "clamp()": {
      syntax: "clamp( <calc-sum>#{3} )"
    },
    "class-selector": {
      syntax: "'.' <ident-token>"
    },
    "clip-source": {
      syntax: "<url>"
    },
    color: {
      syntax: "<color-base> | currentColor | <system-color> | <light-dark()> | <deprecated-system-color>"
    },
    "color()": {
      syntax: "color( [ from <color> ]? <colorspace-params> [ / [ <alpha-value> | none ] ]? )"
    },
    "color-base": {
      syntax: "<hex-color> | <color-function> | <named-color> | <color-mix()> | transparent"
    },
    "color-function": {
      syntax: "<rgb()> | <rgba()> | <hsl()> | <hsla()> | <hwb()> | <lab()> | <lch()> | <oklab()> | <oklch()> | <color()>"
    },
    "color-interpolation-method": {
      syntax: "in [ <rectangular-color-space> | <polar-color-space> <hue-interpolation-method>? | <custom-color-space> ]"
    },
    "color-mix()": {
      syntax: "color-mix( <color-interpolation-method> , [ <color> && <percentage [0,100]>? ]#{2})"
    },
    "color-stop": {
      syntax: "<color-stop-length> | <color-stop-angle>"
    },
    "color-stop-angle": {
      syntax: "[ <angle-percentage> | <zero> ]{1,2}"
    },
    "color-stop-length": {
      syntax: "<length-percentage>{1,2}"
    },
    "color-stop-list": {
      syntax: "<linear-color-stop> , [ <linear-color-hint>? , <linear-color-stop> ]#?"
    },
    "colorspace-params": {
      syntax: "[<custom-params> | <predefined-rgb-params> | <xyz-params>]"
    },
    combinator: {
      syntax: "'>' | '+' | '~' | [ '||' ]"
    },
    "common-lig-values": {
      syntax: "[ common-ligatures | no-common-ligatures ]"
    },
    "compat-auto": {
      syntax: "searchfield | textarea | checkbox | radio | menulist | listbox | meter | progress-bar | button"
    },
    "compat-special": {
      syntax: "textfield | menulist-button"
    },
    "complex-selector": {
      syntax: "<compound-selector> [ <combinator>? <compound-selector> ]*"
    },
    "complex-selector-list": {
      syntax: "<complex-selector>#"
    },
    "composite-style": {
      syntax: "clear | copy | source-over | source-in | source-out | source-atop | destination-over | destination-in | destination-out | destination-atop | xor"
    },
    "compositing-operator": {
      syntax: "add | subtract | intersect | exclude"
    },
    "compound-selector": {
      syntax: "[ <type-selector>? <subclass-selector>* [ <pseudo-element-selector> <pseudo-class-selector>* ]* ]!"
    },
    "compound-selector-list": {
      syntax: "<compound-selector>#"
    },
    "conic-gradient()": {
      syntax: "conic-gradient( [ <conic-gradient-syntax> ] )"
    },
    "conic-gradient-syntax": {
      syntax: "[ [ [ from [ <angle> | <zero> ] ]? [ at <position> ]? ] || <color-interpolation-method> ]? , <angular-color-stop-list>"
    },
    "container-condition": {
      syntax: "[ <container-name>? <container-query>? ]!"
    },
    "container-name": {
      syntax: "<custom-ident>"
    },
    "container-query": {
      syntax: "not <query-in-parens> | <query-in-parens> [ [ and <query-in-parens> ]* | [ or <query-in-parens> ]* ]"
    },
    "content-distribution": {
      syntax: "space-between | space-around | space-evenly | stretch"
    },
    "content-list": {
      syntax: "[ <string> | <image> | <attr()> | <quote> | <counter> ]+"
    },
    "content-position": {
      syntax: "center | start | end | flex-start | flex-end"
    },
    "content-replacement": {
      syntax: "<image>"
    },
    "contextual-alt-values": {
      syntax: "[ contextual | no-contextual ]"
    },
    "contrast()": {
      syntax: "contrast( [ <number> | <percentage> ]? )"
    },
    "coord-box": {
      syntax: "<paint-box> | view-box"
    },
    "corner-shape-value": {
      syntax: "round | scoop | bevel | notch | square | squircle | <superellipse()>"
    },
    "cos()": {
      syntax: "cos( <calc-sum> )"
    },
    counter: {
      syntax: "<counter()> | <counters()>"
    },
    "counter()": {
      syntax: "counter( <counter-name>, <counter-style>? )"
    },
    "counter-name": {
      syntax: "<custom-ident>"
    },
    "counter-style": {
      syntax: "<counter-style-name> | symbols()"
    },
    "counter-style-name": {
      syntax: "<custom-ident>"
    },
    "counters()": {
      syntax: "counters( <counter-name>, <string>, <counter-style>? )"
    },
    "cross-fade()": {
      syntax: "cross-fade( <cf-mixing-image> , <cf-final-image>? )"
    },
    "cubic-bezier()": {
      syntax: "cubic-bezier( [ <number [0,1]>, <number> ]#{2} )"
    },
    "cubic-bezier-easing-function": {
      syntax: "ease | ease-in | ease-out | ease-in-out | <cubic-bezier()>"
    },
    "cursor-predefined": {
      syntax: "auto | default | none | context-menu | help | pointer | progress | wait | cell | crosshair | text | vertical-text | alias | copy | move | no-drop | not-allowed | e-resize | n-resize | ne-resize | nw-resize | s-resize | se-resize | sw-resize | w-resize | ew-resize | ns-resize | nesw-resize | nwse-resize | col-resize | row-resize | all-scroll | zoom-in | zoom-out | grab | grabbing"
    },
    "custom-color-space": {
      syntax: "<dashed-ident>"
    },
    "custom-params": {
      syntax: "<dashed-ident> [ <number> | <percentage> | none ]+"
    },
    dasharray: {
      syntax: "[ [ <length-percentage> | <number> ]+ ]#"
    },
    "dashndashdigit-ident": {
      syntax: "<ident-token>"
    },
    "deprecated-system-color": {
      syntax: "ActiveBorder | ActiveCaption | AppWorkspace | Background | ButtonHighlight | ButtonShadow | CaptionText | InactiveBorder | InactiveCaption | InactiveCaptionText | InfoBackground | InfoText | Menu | MenuText | Scrollbar | ThreeDDarkShadow | ThreeDFace | ThreeDHighlight | ThreeDLightShadow | ThreeDShadow | Window | WindowFrame | WindowText"
    },
    "discretionary-lig-values": {
      syntax: "[ discretionary-ligatures | no-discretionary-ligatures ]"
    },
    "display-box": {
      syntax: "contents | none"
    },
    "display-inside": {
      syntax: "flow | flow-root | table | flex | grid | ruby"
    },
    "display-internal": {
      syntax: "table-row-group | table-header-group | table-footer-group | table-row | table-cell | table-column-group | table-column | table-caption | ruby-base | ruby-text | ruby-base-container | ruby-text-container"
    },
    "display-legacy": {
      syntax: "inline-block | inline-list-item | inline-table | inline-flex | inline-grid"
    },
    "display-listitem": {
      syntax: "<display-outside>? && [ flow | flow-root ]? && list-item"
    },
    "display-outside": {
      syntax: "block | inline | run-in"
    },
    "drop-shadow()": {
      syntax: "drop-shadow( [ <color>? && <length>{2,3} ] )"
    },
    "dynamic-range-limit-mix()": {
      syntax: "dynamic-range-limit-mix( [ <'dynamic-range-limit'> && <percentage [0,100]> ]#{2,} )"
    },
    "easing-function": {
      syntax: "<linear-easing-function> | <cubic-bezier-easing-function> | <step-easing-function>"
    },
    "east-asian-variant-values": {
      syntax: "[ jis78 | jis83 | jis90 | jis04 | simplified | traditional ]"
    },
    "east-asian-width-values": {
      syntax: "[ full-width | proportional-width ]"
    },
    "element()": {
      syntax: "element( <id-selector> )"
    },
    "ellipse()": {
      syntax: "ellipse( <radial-size>? [ at <position> ]? )"
    },
    "env()": {
      syntax: "env( <custom-ident> , <declaration-value>? )"
    },
    "exp()": {
      syntax: "exp( <calc-sum> )"
    },
    "explicit-track-list": {
      syntax: "[ <line-names>? <track-size> ]+ <line-names>?"
    },
    "family-name": {
      syntax: "<string> | <custom-ident>+"
    },
    "feature-tag-value": {
      syntax: "<string> [ <integer> | on | off ]?"
    },
    "feature-type": {
      syntax: "@stylistic | @historical-forms | @styleset | @character-variant | @swash | @ornaments | @annotation"
    },
    "feature-value-block": {
      syntax: "<feature-type> '{' <feature-value-declaration-list> '}'"
    },
    "feature-value-block-list": {
      syntax: "<feature-value-block>+"
    },
    "feature-value-declaration": {
      syntax: "<custom-ident>: <integer>+;"
    },
    "feature-value-declaration-list": {
      syntax: "<feature-value-declaration>"
    },
    "feature-value-name": {
      syntax: "<custom-ident>"
    },
    "filter-function": {
      syntax: "<blur()> | <brightness()> | <contrast()> | <drop-shadow()> | <grayscale()> | <hue-rotate()> | <invert()> | <opacity()> | <saturate()> | <sepia()>"
    },
    "filter-value-list": {
      syntax: "[ <filter-function> | <url> ]+"
    },
    "final-bg-layer": {
      syntax: "<bg-image> || <bg-position> [ / <bg-size> ]? || <repeat-style> || <attachment> || <visual-box> || <visual-box> || <'background-color'>"
    },
    "fit-content()": {
      syntax: "fit-content( <length-percentage [0,∞]> )"
    },
    "fixed-breadth": {
      syntax: "<length-percentage>"
    },
    "fixed-repeat": {
      syntax: "repeat( [ <integer [1,∞]> ] , [ <line-names>? <fixed-size> ]+ <line-names>? )"
    },
    "fixed-size": {
      syntax: "<fixed-breadth> | minmax( <fixed-breadth> , <track-breadth> ) | minmax( <inflexible-breadth> , <fixed-breadth> )"
    },
    "font-stretch-absolute": {
      syntax: "normal | ultra-condensed | extra-condensed | condensed | semi-condensed | semi-expanded | expanded | extra-expanded | ultra-expanded | <percentage>"
    },
    "font-variant-css2": {
      syntax: "normal | small-caps"
    },
    "font-weight-absolute": {
      syntax: "normal | bold | <number [1,1000]>"
    },
    "font-width-css3": {
      syntax: "normal | ultra-condensed | extra-condensed | condensed | semi-condensed | semi-expanded | expanded | extra-expanded | ultra-expanded"
    },
    "form-control-identifier": {
      syntax: "select"
    },
    "frequency-percentage": {
      syntax: "<frequency> | <percentage>"
    },
    "generic-complete": {
      syntax: "serif | sans-serif | system-ui | cursive | fantasy | math | monospace"
    },
    "general-enclosed": {
      syntax: "[ <function-token> <any-value> ) ] | ( <ident> <any-value> )"
    },
    "generic-family": {
      syntax: "<generic-complete> | <generic-incomplete> | emoji | fangsong"
    },
    "generic-incomplete": {
      syntax: "ui-serif | ui-sans-serif | ui-monospace | ui-rounded"
    },
    "geometry-box": {
      syntax: "<shape-box> | fill-box | stroke-box | view-box"
    },
    gradient: {
      syntax: "<linear-gradient()> | <repeating-linear-gradient()> | <radial-gradient()> | <repeating-radial-gradient()> | <conic-gradient()> | <repeating-conic-gradient()>"
    },
    "grayscale()": {
      syntax: "grayscale( [ <number> | <percentage> ]? )"
    },
    "grid-line": {
      syntax: "auto | <custom-ident> | [ <integer> && <custom-ident>? ] | [ span && [ <integer> || <custom-ident> ] ]"
    },
    "historical-lig-values": {
      syntax: "[ historical-ligatures | no-historical-ligatures ]"
    },
    "hsl()": {
      syntax: "hsl( <hue>, <percentage>, <percentage>, <alpha-value>? ) | hsl( [ <hue> | none ] [ <percentage> | <number> | none ] [ <percentage> | <number> | none ] [ / [ <alpha-value> | none ] ]? )"
    },
    "hsla()": {
      syntax: "hsla( <hue>, <percentage>, <percentage>, <alpha-value>? ) | hsla( [ <hue> | none ] [ <percentage> | <number> | none ] [ <percentage> | <number> | none ] [ / [ <alpha-value> | none ] ]? )"
    },
    hue: {
      syntax: "<number> | <angle>"
    },
    "hue-interpolation-method": {
      syntax: "[ shorter | longer | increasing | decreasing ] hue"
    },
    "hue-rotate()": {
      syntax: "hue-rotate( [ <angle> | <zero> ]? )"
    },
    "hwb()": {
      syntax: "hwb( [ <hue> | none ] [ <percentage> | <number> | none ] [ <percentage> | <number> | none ] [ / [ <alpha-value> | none ] ]? )"
    },
    "hypot()": {
      syntax: "hypot( <calc-sum># )"
    },
    "id-selector": {
      syntax: "<hash-token>"
    },
    image: {
      syntax: "<url> | <image()> | <image-set()> | <element()> | <paint()> | <cross-fade()> | <gradient>"
    },
    "image()": {
      syntax: "image( <image-tags>? [ <image-src>? , <color>? ]! )"
    },
    "image-set()": {
      syntax: "image-set( <image-set-option># )"
    },
    "image-set-option": {
      syntax: "[ <image> | <string> ] [ <resolution> || type(<string>) ]"
    },
    "image-src": {
      syntax: "<url> | <string>"
    },
    "image-tags": {
      syntax: "ltr | rtl"
    },
    "inflexible-breadth": {
      syntax: "<length-percentage> | min-content | max-content | auto"
    },
    "inset()": {
      syntax: "inset( <length-percentage>{1,4} [ round <'border-radius'> ]? )"
    },
    integer: {
      syntax: "<number-token>"
    },
    "invert()": {
      syntax: "invert( [ <number> | <percentage> ]? )"
    },
    "keyframe-block": {
      syntax: `<keyframe-selector># {
  <declaration-list>
}`
    },
    "keyframe-selector": {
      syntax: "from | to | <percentage [0,100]> | <timeline-range-name> <percentage>"
    },
    "keyframes-name": {
      syntax: "<custom-ident> | <string>"
    },
    "lab()": {
      syntax: "lab( [<percentage> | <number> | none] [ <percentage> | <number> | none] [ <percentage> | <number> | none] [ / [<alpha-value> | none] ]? )"
    },
    "layer()": {
      syntax: "layer( <layer-name> )"
    },
    "layer-name": {
      syntax: "<ident> [ '.' <ident> ]*"
    },
    "lch()": {
      syntax: "lch( [<percentage> | <number> | none] [ <percentage> | <number> | none] [ <hue> | none] [ / [<alpha-value> | none] ]? )"
    },
    "leader()": {
      syntax: "leader( <leader-type> )"
    },
    "leader-type": {
      syntax: "dotted | solid | space | <string>"
    },
    "length-percentage": {
      syntax: "<length> | <percentage>"
    },
    "light-dark()": {
      syntax: "light-dark( <color>, <color> )"
    },
    "line-name-list": {
      syntax: "[ <line-names> | <name-repeat> ]+"
    },
    "line-names": {
      syntax: "'[' <custom-ident>* ']'"
    },
    "line-style": {
      syntax: "none | hidden | dotted | dashed | solid | double | groove | ridge | inset | outset"
    },
    "line-width": {
      syntax: "<length> | thin | medium | thick"
    },
    "linear()": {
      syntax: "linear( [ <number> && <percentage>{0,2} ]# )"
    },
    "linear-color-hint": {
      syntax: "<length-percentage>"
    },
    "linear-color-stop": {
      syntax: "<color> <color-stop-length>?"
    },
    "linear-easing-function": {
      syntax: "linear | <linear()>"
    },
    "linear-gradient()": {
      syntax: "linear-gradient( [ <linear-gradient-syntax> ] )"
    },
    "linear-gradient-syntax": {
      syntax: "[ [ <angle> | <zero> | to <side-or-corner> ] || <color-interpolation-method> ]? , <color-stop-list>"
    },
    "log()": {
      syntax: "log( <calc-sum>, <calc-sum>? )"
    },
    "mask-layer": {
      syntax: "<mask-reference> || <position> [ / <bg-size> ]? || <repeat-style> || <geometry-box> || [ <geometry-box> | no-clip ] || <compositing-operator> || <masking-mode>"
    },
    "mask-position": {
      syntax: "[ <length-percentage> | left | center | right ] [ <length-percentage> | top | center | bottom ]?"
    },
    "mask-reference": {
      syntax: "none | <image> | <mask-source>"
    },
    "mask-source": {
      syntax: "<url>"
    },
    "masking-mode": {
      syntax: "alpha | luminance | match-source"
    },
    "matrix()": {
      syntax: "matrix( <number>#{6} )"
    },
    "matrix3d()": {
      syntax: "matrix3d( <number>#{16} )"
    },
    "max()": {
      syntax: "max( <calc-sum># )"
    },
    "media-and": {
      syntax: "<media-in-parens> [ and <media-in-parens> ]+"
    },
    "media-condition": {
      syntax: "<media-not> | <media-and> | <media-or> | <media-in-parens>"
    },
    "media-condition-without-or": {
      syntax: "<media-not> | <media-and> | <media-in-parens>"
    },
    "media-feature": {
      syntax: "( [ <mf-plain> | <mf-boolean> | <mf-range> ] )"
    },
    "media-in-parens": {
      syntax: "( <media-condition> ) | <media-feature> | <general-enclosed>"
    },
    "media-not": {
      syntax: "not <media-in-parens>"
    },
    "media-or": {
      syntax: "<media-in-parens> [ or <media-in-parens> ]+"
    },
    "media-query": {
      syntax: "<media-condition> | [ not | only ]? <media-type> [ and <media-condition-without-or> ]?"
    },
    "media-query-list": {
      syntax: "<media-query>#"
    },
    "media-type": {
      syntax: "<ident>"
    },
    "mf-boolean": {
      syntax: "<mf-name>"
    },
    "mf-name": {
      syntax: "<ident>"
    },
    "mf-plain": {
      syntax: "<mf-name> : <mf-value>"
    },
    "mf-range": {
      syntax: `<mf-name> [ '<' | '>' ]? '='? <mf-value>
| <mf-value> [ '<' | '>' ]? '='? <mf-name>
| <mf-value> '<' '='? <mf-name> '<' '='? <mf-value>
| <mf-value> '>' '='? <mf-name> '>' '='? <mf-value>`
    },
    "mf-value": {
      syntax: "<number> | <dimension> | <ident> | <ratio>"
    },
    "min()": {
      syntax: "min( <calc-sum># )"
    },
    "minmax()": {
      syntax: "minmax( [ <length-percentage> | min-content | max-content | auto ] , [ <length-percentage> | <flex> | min-content | max-content | auto ] )"
    },
    "mod()": {
      syntax: "mod( <calc-sum>, <calc-sum> )"
    },
    "n-dimension": {
      syntax: "<dimension-token>"
    },
    "name-repeat": {
      syntax: "repeat( [ <integer [1,∞]> | auto-fill ], <line-names>+ )"
    },
    "named-color": {
      syntax: "aliceblue | antiquewhite | aqua | aquamarine | azure | beige | bisque | black | blanchedalmond | blue | blueviolet | brown | burlywood | cadetblue | chartreuse | chocolate | coral | cornflowerblue | cornsilk | crimson | cyan | darkblue | darkcyan | darkgoldenrod | darkgray | darkgreen | darkgrey | darkkhaki | darkmagenta | darkolivegreen | darkorange | darkorchid | darkred | darksalmon | darkseagreen | darkslateblue | darkslategray | darkslategrey | darkturquoise | darkviolet | deeppink | deepskyblue | dimgray | dimgrey | dodgerblue | firebrick | floralwhite | forestgreen | fuchsia | gainsboro | ghostwhite | gold | goldenrod | gray | green | greenyellow | grey | honeydew | hotpink | indianred | indigo | ivory | khaki | lavender | lavenderblush | lawngreen | lemonchiffon | lightblue | lightcoral | lightcyan | lightgoldenrodyellow | lightgray | lightgreen | lightgrey | lightpink | lightsalmon | lightseagreen | lightskyblue | lightslategray | lightslategrey | lightsteelblue | lightyellow | lime | limegreen | linen | magenta | maroon | mediumaquamarine | mediumblue | mediumorchid | mediumpurple | mediumseagreen | mediumslateblue | mediumspringgreen | mediumturquoise | mediumvioletred | midnightblue | mintcream | mistyrose | moccasin | navajowhite | navy | oldlace | olive | olivedrab | orange | orangered | orchid | palegoldenrod | palegreen | paleturquoise | palevioletred | papayawhip | peachpuff | peru | pink | plum | powderblue | purple | rebeccapurple | red | rosybrown | royalblue | saddlebrown | salmon | sandybrown | seagreen | seashell | sienna | silver | skyblue | slateblue | slategray | slategrey | snow | springgreen | steelblue | tan | teal | thistle | tomato | turquoise | violet | wheat | white | whitesmoke | yellow | yellowgreen"
    },
    "namespace-prefix": {
      syntax: "<ident>"
    },
    "ndash-dimension": {
      syntax: "<dimension-token>"
    },
    "ndashdigit-dimension": {
      syntax: "<dimension-token>"
    },
    "ndashdigit-ident": {
      syntax: "<ident-token>"
    },
    "ns-prefix": {
      syntax: "[ <ident-token> | '*' ]? '|'"
    },
    "number-percentage": {
      syntax: "<number> | <percentage>"
    },
    "numeric-figure-values": {
      syntax: "[ lining-nums | oldstyle-nums ]"
    },
    "numeric-fraction-values": {
      syntax: "[ diagonal-fractions | stacked-fractions ]"
    },
    "numeric-spacing-values": {
      syntax: "[ proportional-nums | tabular-nums ]"
    },
    "offset-path": {
      syntax: "<ray()> | <url> | <basic-shape>"
    },
    "oklab()": {
      syntax: "oklab( [ <percentage> | <number> | none] [ <percentage> | <number> | none] [ <percentage> | <number> | none] [ / [<alpha-value> | none] ]? )"
    },
    "oklch()": {
      syntax: "oklch( [ <percentage> | <number> | none] [ <percentage> | <number> | none] [ <hue> | none] [ / [<alpha-value> | none] ]? )"
    },
    "opacity()": {
      syntax: "opacity( [ <number> | <percentage> ]? )"
    },
    "opacity-value": {
      syntax: "<number> | <percentage>"
    },
    "outline-line-style": {
      syntax: "none | dotted | dashed | solid | double | groove | ridge | inset | outset"
    },
    "outline-radius": {
      syntax: "<length> | <percentage>"
    },
    "overflow-position": {
      syntax: "unsafe | safe"
    },
    "page-body": {
      syntax: "<declaration>? [ ; <page-body> ]? | <page-margin-box> <page-body>"
    },
    "page-margin-box": {
      syntax: "<page-margin-box-type> '{' <declaration-list> '}'"
    },
    "page-margin-box-type": {
      syntax: "@top-left-corner | @top-left | @top-center | @top-right | @top-right-corner | @bottom-left-corner | @bottom-left | @bottom-center | @bottom-right | @bottom-right-corner | @left-top | @left-middle | @left-bottom | @right-top | @right-middle | @right-bottom"
    },
    "page-selector": {
      syntax: "<pseudo-page>+ | <ident> <pseudo-page>*"
    },
    "page-selector-list": {
      syntax: "[ <page-selector># ]?"
    },
    "page-size": {
      syntax: "A5 | A4 | A3 | B5 | B4 | JIS-B5 | JIS-B4 | letter | legal | ledger"
    },
    paint: {
      syntax: "none | <color> | <url> [none | <color>]? | context-fill | context-stroke"
    },
    "paint()": {
      syntax: "paint( <ident>, <declaration-value>? )"
    },
    "paint-box": {
      syntax: "<visual-box> | fill-box | stroke-box"
    },
    "palette-identifier": {
      syntax: "<dashed-ident>"
    },
    "palette-mix()": {
      syntax: "palette-mix(<color-interpolation-method> , [ [normal | light | dark | <palette-identifier> | <palette-mix()> ] && <percentage [0,100]>? ]#{2})"
    },
    "path()": {
      syntax: "path( <'fill-rule'>? , <string> )"
    },
    "perspective()": {
      syntax: "perspective( [ <length [0,∞]> | none ] )"
    },
    "polar-color-space": {
      syntax: "hsl | hwb | lch | oklch"
    },
    "polygon()": {
      syntax: "polygon( <'fill-rule'>? , [ <length-percentage> <length-percentage> ]# )"
    },
    position: {
      syntax: "[ [ left | center | right ] || [ top | center | bottom ] | [ left | center | right | <length-percentage> ] [ top | center | bottom | <length-percentage> ]? | [ [ left | right ] <length-percentage> ] && [ [ top | bottom ] <length-percentage> ] ]"
    },
    "position-area": {
      syntax: "[ left | center | right | span-left | span-right | x-start | x-end | span-x-start | span-x-end | x-self-start | x-self-end | span-x-self-start | span-x-self-end | span-all ] || [ top | center | bottom | span-top | span-bottom | y-start | y-end | span-y-start | span-y-end | y-self-start | y-self-end | span-y-self-start | span-y-self-end | span-all ] | [ block-start | center | block-end | span-block-start | span-block-end | span-all ] || [ inline-start | center | inline-end | span-inline-start | span-inline-end | span-all ] | [ self-block-start | center | self-block-end | span-self-block-start | span-self-block-end | span-all ] || [ self-inline-start | center | self-inline-end | span-self-inline-start | span-self-inline-end | span-all ] | [ start | center | end | span-start | span-end | span-all ]{1,2} | [ self-start | center | self-end | span-self-start | span-self-end | span-all ]{1,2}"
    },
    "pow()": {
      syntax: "pow( <calc-sum>, <calc-sum> )"
    },
    "predefined-rgb": {
      syntax: "srgb | srgb-linear | display-p3 | display-p3-linear | a98-rgb | prophoto-rgb | rec2020"
    },
    "predefined-rgb-params": {
      syntax: "<predefined-rgb> [ <number> | <percentage> | none ]{3}"
    },
    "pseudo-class-selector": {
      syntax: "':' <ident-token> | ':' <function-token> <any-value> ')'"
    },
    "pseudo-element-selector": {
      syntax: "':' <pseudo-class-selector>"
    },
    "pseudo-page": {
      syntax: ": [ left | right | first | blank ]"
    },
    "query-in-parens": {
      syntax: "( <container-query> ) | ( <size-feature> ) | style( <style-query> ) | scroll-state( <scroll-state-query> ) | <general-enclosed>"
    },
    quote: {
      syntax: "open-quote | close-quote | no-open-quote | no-close-quote"
    },
    "radial-extent": {
      syntax: "closest-corner | closest-side | farthest-corner | farthest-side"
    },
    "radial-gradient()": {
      syntax: "radial-gradient( [ <radial-gradient-syntax> ] )"
    },
    "radial-gradient-syntax": {
      syntax: "[ [ [ <radial-shape> || <radial-size> ]? [ at <position> ]? ] || <color-interpolation-method> ]? , <color-stop-list>"
    },
    "radial-shape": {
      syntax: "circle | ellipse"
    },
    "radial-size": {
      syntax: "<radial-extent> | <length [0,∞]> | <length-percentage [0,∞]>{2}"
    },
    ratio: {
      syntax: "<number [0,∞]> [ / <number [0,∞]> ]?"
    },
    "ray()": {
      syntax: "ray( <angle> && <ray-size>? && contain? && [at <position>]? )"
    },
    "ray-size": {
      syntax: "closest-side | closest-corner | farthest-side | farthest-corner | sides"
    },
    "rect()": {
      syntax: "rect( [ <length-percentage> | auto ]{4} [ round <'border-radius'> ]? )"
    },
    "rectangular-color-space": {
      syntax: "srgb | srgb-linear | display-p3 | display-p3-linear | a98-rgb | prophoto-rgb | rec2020 | lab | oklab | xyz | xyz-d50 | xyz-d65"
    },
    "relative-selector": {
      syntax: "<combinator>? <complex-selector>"
    },
    "relative-selector-list": {
      syntax: "<relative-selector>#"
    },
    "relative-size": {
      syntax: "larger | smaller"
    },
    "rem()": {
      syntax: "rem( <calc-sum>, <calc-sum> )"
    },
    "repeat-style": {
      syntax: "repeat-x | repeat-y | [ repeat | space | round | no-repeat ]{1,2}"
    },
    "repeating-conic-gradient()": {
      syntax: "repeating-conic-gradient( [ <conic-gradient-syntax> ] )"
    },
    "repeating-linear-gradient()": {
      syntax: "repeating-linear-gradient( [ <linear-gradient-syntax> ] )"
    },
    "repeating-radial-gradient()": {
      syntax: "repeating-radial-gradient( [ <radial-gradient-syntax> ] )"
    },
    "reversed-counter-name": {
      syntax: "reversed( <counter-name> )"
    },
    "rgb()": {
      syntax: "rgb( <percentage>#{3} , <alpha-value>? ) | rgb( <number>#{3} , <alpha-value>? ) | rgb( [ <number> | <percentage> | none ]{3} [ / [ <alpha-value> | none ] ]? )"
    },
    "rgba()": {
      syntax: "rgba( <percentage>#{3} , <alpha-value>? ) | rgba( <number>#{3} , <alpha-value>? ) | rgba( [ <number> | <percentage> | none ]{3} [ / [ <alpha-value> | none ] ]? )"
    },
    "rotate()": {
      syntax: "rotate( [ <angle> | <zero> ] )"
    },
    "rotate3d()": {
      syntax: "rotate3d( <number> , <number> , <number> , [ <angle> | <zero> ] )"
    },
    "rotateX()": {
      syntax: "rotateX( [ <angle> | <zero> ] )"
    },
    "rotateY()": {
      syntax: "rotateY( [ <angle> | <zero> ] )"
    },
    "rotateZ()": {
      syntax: "rotateZ( [ <angle> | <zero> ] )"
    },
    "round()": {
      syntax: "round( <rounding-strategy>?, <calc-sum>, <calc-sum> )"
    },
    "rounding-strategy": {
      syntax: "nearest | up | down | to-zero"
    },
    "saturate()": {
      syntax: "saturate( [ <number> | <percentage> ]? )"
    },
    "scale()": {
      syntax: "scale( [ <number> | <percentage> ]#{1,2} )"
    },
    "scale3d()": {
      syntax: "scale3d( [ <number> | <percentage> ]#{3} )"
    },
    "scaleX()": {
      syntax: "scaleX( [ <number> | <percentage> ] )"
    },
    "scaleY()": {
      syntax: "scaleY( [ <number> | <percentage> ] )"
    },
    "scaleZ()": {
      syntax: "scaleZ( [ <number> | <percentage> ] )"
    },
    "scope-end": {
      syntax: "<selector-list>"
    },
    "scope-start": {
      syntax: "<selector-list>"
    },
    "scroll()": {
      syntax: "scroll( [ <scroller> || <axis> ]? )"
    },
    scroller: {
      syntax: "root | nearest | self"
    },
    "scroll-state-feature": {
      syntax: "<media-query-list>"
    },
    "scroll-state-in-parens": {
      syntax: "( <scroll-state-query> ) | ( <scroll-state-feature> ) | <general-enclosed>"
    },
    "scroll-state-query": {
      syntax: "not <scroll-state-in-parens> | <scroll-state-in-parens> [ [ and <scroll-state-in-parens> ]* | [ or <scroll-state-in-parens> ]* ] | <scroll-state-feature>"
    },
    "selector-list": {
      syntax: "<complex-selector-list>"
    },
    "self-position": {
      syntax: "center | start | end | self-start | self-end | flex-start | flex-end"
    },
    "sepia()": {
      syntax: "sepia( [ <number> | <percentage> ]? )"
    },
    shadow: {
      syntax: "inset? && <length>{2,4} && <color>?"
    },
    "shadow-t": {
      syntax: "[ <length>{2,3} && <color>? ]"
    },
    shape: {
      syntax: "rect(<top>, <right>, <bottom>, <left>)"
    },
    "shape-box": {
      syntax: "<visual-box> | margin-box"
    },
    "side-or-corner": {
      syntax: "[ left | right ] || [ top | bottom ]"
    },
    "sign()": {
      syntax: "sign( <calc-sum> )"
    },
    "signed-integer": {
      syntax: "<number-token>"
    },
    "signless-integer": {
      syntax: "<number-token>"
    },
    "sin()": {
      syntax: "sin( <calc-sum> )"
    },
    "single-animation": {
      syntax: "<'animation-duration'> || <easing-function> || <'animation-delay'> || <single-animation-iteration-count> || <single-animation-direction> || <single-animation-fill-mode> || <single-animation-play-state> || [ none | <keyframes-name> ] || <single-animation-timeline>"
    },
    "single-animation-composition": {
      syntax: "replace | add | accumulate"
    },
    "single-animation-direction": {
      syntax: "normal | reverse | alternate | alternate-reverse"
    },
    "single-animation-fill-mode": {
      syntax: "none | forwards | backwards | both"
    },
    "single-animation-iteration-count": {
      syntax: "infinite | <number>"
    },
    "single-animation-play-state": {
      syntax: "running | paused"
    },
    "single-animation-timeline": {
      syntax: "auto | none | <dashed-ident> | <scroll()> | <view()>"
    },
    "single-transition": {
      syntax: "[ none | <single-transition-property> ] || <time> || <easing-function> || <time> || <transition-behavior-value>"
    },
    "single-transition-property": {
      syntax: "all | <custom-ident>"
    },
    size: {
      syntax: "closest-side | farthest-side | closest-corner | farthest-corner | <length> | <length-percentage>{2}"
    },
    "size-feature": {
      syntax: "<media-query-list>"
    },
    "skew()": {
      syntax: "skew( [ <angle> | <zero> ] , [ <angle> | <zero> ]? )"
    },
    "skewX()": {
      syntax: "skewX( [ <angle> | <zero> ] )"
    },
    "skewY()": {
      syntax: "skewY( [ <angle> | <zero> ] )"
    },
    "sqrt()": {
      syntax: "sqrt( <calc-sum> )"
    },
    "step-position": {
      syntax: "jump-start | jump-end | jump-none | jump-both | start | end"
    },
    "step-easing-function": {
      syntax: "step-start | step-end | <steps()>"
    },
    "steps()": {
      syntax: "steps( <integer>, <step-position>? )"
    },
    "style-feature": {
      syntax: "<declaration>"
    },
    "style-in-parens": {
      syntax: "( <style-query> ) | ( <style-feature> ) | <general-enclosed>"
    },
    "style-query": {
      syntax: "not <style-in-parens> | <style-in-parens> [ [ and <style-in-parens> ]* | [ or <style-in-parens> ]* ] | <style-feature>"
    },
    "subclass-selector": {
      syntax: "<id-selector> | <class-selector> | <attribute-selector> | <pseudo-class-selector>"
    },
    "superellipse()": {
      syntax: "superellipse( [ <number> | infinity | -infinity ] )"
    },
    "supports-condition": {
      syntax: "not <supports-in-parens> | <supports-in-parens> [ and <supports-in-parens> ]* | <supports-in-parens> [ or <supports-in-parens> ]*"
    },
    "supports-decl": {
      syntax: "( <declaration> )"
    },
    "supports-feature": {
      syntax: "<supports-decl> | <supports-selector-fn>"
    },
    "supports-in-parens": {
      syntax: "( <supports-condition> ) | <supports-feature> | <general-enclosed>"
    },
    "supports-selector-fn": {
      syntax: "selector( <complex-selector> )"
    },
    symbol: {
      syntax: "<string> | <image> | <custom-ident>"
    },
    "symbols()": {
      syntax: "symbols( <symbols-type>? [ <string> | <image> ]+ )"
    },
    "symbols-type": {
      syntax: "cyclic | numeric | alphabetic | symbolic | fixed"
    },
    "system-color": {
      syntax: "AccentColor | AccentColorText | ActiveText | ButtonBorder | ButtonFace | ButtonText | Canvas | CanvasText | Field | FieldText | GrayText | Highlight | HighlightText | LinkText | Mark | MarkText | SelectedItem | SelectedItemText | VisitedText"
    },
    "system-family-name": {
      syntax: "caption | icon | menu | message-box | small-caption | status-bar"
    },
    "tan()": {
      syntax: "tan( <calc-sum> )"
    },
    target: {
      syntax: "<target-counter()> | <target-counters()> | <target-text()>"
    },
    "target-counter()": {
      syntax: "target-counter( [ <string> | <url> ] , <custom-ident> , <counter-style>? )"
    },
    "target-counters()": {
      syntax: "target-counters( [ <string> | <url> ] , <custom-ident> , <string> , <counter-style>? )"
    },
    "target-text()": {
      syntax: "target-text( [ <string> | <url> ] , [ content | before | after | first-letter ]? )"
    },
    "text-edge": {
      syntax: "[ text | cap | ex | ideographic | ideographic-ink ] [ text | alphabetic | ideographic | ideographic-ink ]?"
    },
    "time-percentage": {
      syntax: "<time> | <percentage>"
    },
    "timeline-range-name": {
      syntax: "cover | contain | entry | exit | entry-crossing | exit-crossing"
    },
    "track-breadth": {
      syntax: "<length-percentage> | <flex> | min-content | max-content | auto"
    },
    "track-list": {
      syntax: "[ <line-names>? [ <track-size> | <track-repeat> ] ]+ <line-names>?"
    },
    "track-repeat": {
      syntax: "repeat( [ <integer [1,∞]> ] , [ <line-names>? <track-size> ]+ <line-names>? )"
    },
    "track-size": {
      syntax: "<track-breadth> | minmax( <inflexible-breadth> , <track-breadth> ) | fit-content( <length-percentage> )"
    },
    "transform-function": {
      syntax: "<matrix()> | <translate()> | <translateX()> | <translateY()> | <scale()> | <scaleX()> | <scaleY()> | <rotate()> | <skew()> | <skewX()> | <skewY()> | <matrix3d()> | <translate3d()> | <translateZ()> | <scale3d()> | <scaleZ()> | <rotate3d()> | <rotateX()> | <rotateY()> | <rotateZ()> | <perspective()>"
    },
    "transform-list": {
      syntax: "<transform-function>+"
    },
    "transition-behavior-value": {
      syntax: "normal | allow-discrete"
    },
    "translate()": {
      syntax: "translate( <length-percentage> , <length-percentage>? )"
    },
    "translate3d()": {
      syntax: "translate3d( <length-percentage> , <length-percentage> , <length> )"
    },
    "translateX()": {
      syntax: "translateX( <length-percentage> )"
    },
    "translateY()": {
      syntax: "translateY( <length-percentage> )"
    },
    "translateZ()": {
      syntax: "translateZ( <length> )"
    },
    "try-size": {
      syntax: "most-width | most-height | most-block-size | most-inline-size"
    },
    "try-tactic": {
      syntax: "flip-block || flip-inline || flip-start"
    },
    "type-or-unit": {
      syntax: "string | color | url | integer | number | length | angle | time | frequency | cap | ch | em | ex | ic | lh | rlh | rem | vb | vi | vw | vh | vmin | vmax | mm | Q | cm | in | pt | pc | px | deg | grad | rad | turn | ms | s | Hz | kHz | %"
    },
    "type-selector": {
      syntax: "<wq-name> | <ns-prefix>? '*'"
    },
    "var()": {
      syntax: "var( <custom-property-name> , <declaration-value>? )"
    },
    "view()": {
      syntax: "view([<axis> || <'view-timeline-inset'>]?)"
    },
    "viewport-length": {
      syntax: "auto | <length-percentage>"
    },
    "visual-box": {
      syntax: "content-box | padding-box | border-box"
    },
    "wq-name": {
      syntax: "<ns-prefix>? <ident-token>"
    },
    "xywh()": {
      syntax: "xywh( <length-percentage>{2} <length-percentage [0,∞]>{2} [ round <'border-radius'> ]? )"
    },
    xyz: {
      syntax: "xyz | xyz-d50 | xyz-d65"
    },
    "xyz-params": {
      syntax: "<xyz> [ <number> | <percentage> | none ]{3}"
    }
  };
});

// ../imp-pinned/node_modules/css-tree/cjs/data.cjs
var require_data = __commonJS((exports, module) => {
  var dataPatch = require_data_patch();
  var mdnAtrules = require_at_rules();
  var mdnProperties = require_properties();
  var mdnSyntaxes = require_syntaxes();
  var hasOwn = Object.hasOwn || ((object, property) => Object.prototype.hasOwnProperty.call(object, property));
  var extendSyntax = /^\s*\|\s*/;
  function preprocessAtrules(dict) {
    const result = Object.create(null);
    for (const [atruleName, atrule] of Object.entries(dict)) {
      let descriptors = null;
      if (atrule.descriptors) {
        descriptors = Object.create(null);
        for (const [name, descriptor] of Object.entries(atrule.descriptors)) {
          descriptors[name] = descriptor.syntax;
        }
      }
      result[atruleName.substr(1)] = {
        prelude: atrule.syntax.trim().replace(/\{(.|\s)+\}/, "").match(/^@\S+\s+([^;\{]*)/)[1].trim() || null,
        descriptors
      };
    }
    return result;
  }
  function patchDictionary(dict, patchDict) {
    const result = Object.create(null);
    for (const [key, value] of Object.entries(dict)) {
      if (value) {
        result[key] = value.syntax || value;
      }
    }
    for (const key of Object.keys(patchDict)) {
      if (hasOwn(dict, key)) {
        if (patchDict[key].syntax) {
          result[key] = extendSyntax.test(patchDict[key].syntax) ? result[key] + " " + patchDict[key].syntax.trim() : patchDict[key].syntax;
        } else {
          delete result[key];
        }
      } else {
        if (patchDict[key].syntax) {
          result[key] = patchDict[key].syntax.replace(extendSyntax, "");
        }
      }
    }
    return result;
  }
  function preprocessPatchAtrulesDescritors(declarations) {
    const result = {};
    for (const [key, value] of Object.entries(declarations || {})) {
      result[key] = typeof value === "string" ? { syntax: value } : value;
    }
    return result;
  }
  function patchAtrules(dict, patchDict) {
    const result = {};
    for (const key in dict) {
      if (patchDict[key] === null) {
        continue;
      }
      const atrulePatch = patchDict[key] || {};
      result[key] = {
        prelude: key in patchDict && "prelude" in atrulePatch ? atrulePatch.prelude : dict[key].prelude || null,
        descriptors: patchDictionary(dict[key].descriptors || {}, preprocessPatchAtrulesDescritors(atrulePatch.descriptors))
      };
    }
    for (const [key, atrulePatch] of Object.entries(patchDict)) {
      if (atrulePatch && !hasOwn(dict, key)) {
        result[key] = {
          prelude: atrulePatch.prelude || null,
          descriptors: atrulePatch.descriptors ? patchDictionary({}, preprocessPatchAtrulesDescritors(atrulePatch.descriptors)) : null
        };
      }
    }
    return result;
  }
  var definitions = {
    types: patchDictionary(mdnSyntaxes, dataPatch.types),
    atrules: patchAtrules(preprocessAtrules(mdnAtrules), dataPatch.atrules),
    properties: patchDictionary(mdnProperties, dataPatch.properties)
  };
  module.exports = definitions;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/AnPlusB.cjs
var require_AnPlusB = __commonJS((exports) => {
  var types2 = require_types();
  var charCodeDefinitions = require_char_code_definitions();
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var N = 110;
  var DISALLOW_SIGN = true;
  var ALLOW_SIGN = false;
  function checkInteger(offset, disallowSign) {
    let pos = this.tokenStart + offset;
    const code = this.charCodeAt(pos);
    if (code === PLUSSIGN || code === HYPHENMINUS) {
      if (disallowSign) {
        this.error("Number sign is not allowed");
      }
      pos++;
    }
    for (;pos < this.tokenEnd; pos++) {
      if (!charCodeDefinitions.isDigit(this.charCodeAt(pos))) {
        this.error("Integer is expected", pos);
      }
    }
  }
  function checkTokenIsInteger(disallowSign) {
    return checkInteger.call(this, 0, disallowSign);
  }
  function expectCharCode(offset, code) {
    if (!this.cmpChar(this.tokenStart + offset, code)) {
      let msg = "";
      switch (code) {
        case N:
          msg = "N is expected";
          break;
        case HYPHENMINUS:
          msg = "HyphenMinus is expected";
          break;
      }
      this.error(msg, this.tokenStart + offset);
    }
  }
  function consumeB() {
    let offset = 0;
    let sign = 0;
    let type = this.tokenType;
    while (type === types2.WhiteSpace || type === types2.Comment) {
      type = this.lookupType(++offset);
    }
    if (type !== types2.Number) {
      if (this.isDelim(PLUSSIGN, offset) || this.isDelim(HYPHENMINUS, offset)) {
        sign = this.isDelim(PLUSSIGN, offset) ? PLUSSIGN : HYPHENMINUS;
        do {
          type = this.lookupType(++offset);
        } while (type === types2.WhiteSpace || type === types2.Comment);
        if (type !== types2.Number) {
          this.skip(offset);
          checkTokenIsInteger.call(this, DISALLOW_SIGN);
        }
      } else {
        return null;
      }
    }
    if (offset > 0) {
      this.skip(offset);
    }
    if (sign === 0) {
      type = this.charCodeAt(this.tokenStart);
      if (type !== PLUSSIGN && type !== HYPHENMINUS) {
        this.error("Number sign is expected");
      }
    }
    checkTokenIsInteger.call(this, sign !== 0);
    return sign === HYPHENMINUS ? "-" + this.consume(types2.Number) : this.consume(types2.Number);
  }
  var name = "AnPlusB";
  var structure = {
    a: [String, null],
    b: [String, null]
  };
  function parse3() {
    const start = this.tokenStart;
    let a = null;
    let b = null;
    if (this.tokenType === types2.Number) {
      checkTokenIsInteger.call(this, ALLOW_SIGN);
      b = this.consume(types2.Number);
    } else if (this.tokenType === types2.Ident && this.cmpChar(this.tokenStart, HYPHENMINUS)) {
      a = "-1";
      expectCharCode.call(this, 1, N);
      switch (this.tokenEnd - this.tokenStart) {
        case 2:
          this.next();
          b = consumeB.call(this);
          break;
        case 3:
          expectCharCode.call(this, 2, HYPHENMINUS);
          this.next();
          this.skipSC();
          checkTokenIsInteger.call(this, DISALLOW_SIGN);
          b = "-" + this.consume(types2.Number);
          break;
        default:
          expectCharCode.call(this, 2, HYPHENMINUS);
          checkInteger.call(this, 3, DISALLOW_SIGN);
          this.next();
          b = this.substrToCursor(start + 2);
      }
    } else if (this.tokenType === types2.Ident || this.isDelim(PLUSSIGN) && this.lookupType(1) === types2.Ident) {
      let sign = 0;
      a = "1";
      if (this.isDelim(PLUSSIGN)) {
        sign = 1;
        this.next();
      }
      expectCharCode.call(this, 0, N);
      switch (this.tokenEnd - this.tokenStart) {
        case 1:
          this.next();
          b = consumeB.call(this);
          break;
        case 2:
          expectCharCode.call(this, 1, HYPHENMINUS);
          this.next();
          this.skipSC();
          checkTokenIsInteger.call(this, DISALLOW_SIGN);
          b = "-" + this.consume(types2.Number);
          break;
        default:
          expectCharCode.call(this, 1, HYPHENMINUS);
          checkInteger.call(this, 2, DISALLOW_SIGN);
          this.next();
          b = this.substrToCursor(start + sign + 1);
      }
    } else if (this.tokenType === types2.Dimension) {
      const code = this.charCodeAt(this.tokenStart);
      const sign = code === PLUSSIGN || code === HYPHENMINUS;
      let i = this.tokenStart + sign;
      for (;i < this.tokenEnd; i++) {
        if (!charCodeDefinitions.isDigit(this.charCodeAt(i))) {
          break;
        }
      }
      if (i === this.tokenStart + sign) {
        this.error("Integer is expected", this.tokenStart + sign);
      }
      expectCharCode.call(this, i - this.tokenStart, N);
      a = this.substring(start, i);
      if (i + 1 === this.tokenEnd) {
        this.next();
        b = consumeB.call(this);
      } else {
        expectCharCode.call(this, i - this.tokenStart + 1, HYPHENMINUS);
        if (i + 2 === this.tokenEnd) {
          this.next();
          this.skipSC();
          checkTokenIsInteger.call(this, DISALLOW_SIGN);
          b = "-" + this.consume(types2.Number);
        } else {
          checkInteger.call(this, i - this.tokenStart + 2, DISALLOW_SIGN);
          this.next();
          b = this.substrToCursor(i + 1);
        }
      }
    } else {
      this.error();
    }
    if (a !== null && a.charCodeAt(0) === PLUSSIGN) {
      a = a.substr(1);
    }
    if (b !== null && b.charCodeAt(0) === PLUSSIGN) {
      b = b.substr(1);
    }
    return {
      type: "AnPlusB",
      loc: this.getLocation(start, this.tokenStart),
      a,
      b
    };
  }
  function generate2(node2) {
    if (node2.a) {
      const a = node2.a === "+1" && "n" || node2.a === "1" && "n" || node2.a === "-1" && "-n" || node2.a + "n";
      if (node2.b) {
        const b = node2.b[0] === "-" || node2.b[0] === "+" ? node2.b : "+" + node2.b;
        this.tokenize(a + b);
      } else {
        this.tokenize(a);
      }
    } else {
      this.tokenize(node2.b);
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Atrule.cjs
var require_Atrule = __commonJS((exports) => {
  var types2 = require_types();
  function consumeRaw() {
    return this.Raw(this.consumeUntilLeftCurlyBracketOrSemicolon, true);
  }
  function isDeclarationBlockAtrule() {
    for (let offset = 1, type;type = this.lookupType(offset); offset++) {
      if (type === types2.RightCurlyBracket) {
        return true;
      }
      if (type === types2.LeftCurlyBracket || type === types2.AtKeyword) {
        return false;
      }
    }
    return false;
  }
  var name = "Atrule";
  var walkContext = "atrule";
  var structure = {
    name: String,
    prelude: ["AtrulePrelude", "Raw", null],
    block: ["Block", null]
  };
  function parse3(isDeclaration = false) {
    const start = this.tokenStart;
    let name2;
    let nameLowerCase;
    let prelude = null;
    let block = null;
    this.eat(types2.AtKeyword);
    name2 = this.substrToCursor(start + 1);
    nameLowerCase = name2.toLowerCase();
    this.skipSC();
    if (this.eof === false && this.tokenType !== types2.LeftCurlyBracket && this.tokenType !== types2.Semicolon) {
      if (this.parseAtrulePrelude) {
        prelude = this.parseWithFallback(this.AtrulePrelude.bind(this, name2, isDeclaration), consumeRaw);
      } else {
        prelude = consumeRaw.call(this, this.tokenIndex);
      }
      this.skipSC();
    }
    switch (this.tokenType) {
      case types2.Semicolon:
        this.next();
        break;
      case types2.LeftCurlyBracket:
        if (hasOwnProperty.call(this.atrule, nameLowerCase) && typeof this.atrule[nameLowerCase].block === "function") {
          block = this.atrule[nameLowerCase].block.call(this, isDeclaration);
        } else {
          block = this.Block(isDeclarationBlockAtrule.call(this));
        }
        break;
    }
    return {
      type: "Atrule",
      loc: this.getLocation(start, this.tokenStart),
      name: name2,
      prelude,
      block
    };
  }
  function generate2(node2) {
    this.token(types2.AtKeyword, "@" + node2.name);
    if (node2.prelude !== null) {
      this.node(node2.prelude);
    }
    if (node2.block) {
      this.node(node2.block);
    } else {
      this.token(types2.Semicolon, ";");
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/AtrulePrelude.cjs
var require_AtrulePrelude = __commonJS((exports) => {
  var types2 = require_types();
  var name = "AtrulePrelude";
  var walkContext = "atrulePrelude";
  var structure = {
    children: [[]]
  };
  function parse3(name2) {
    let children = null;
    if (name2 !== null) {
      name2 = name2.toLowerCase();
    }
    this.skipSC();
    if (hasOwnProperty.call(this.atrule, name2) && typeof this.atrule[name2].prelude === "function") {
      children = this.atrule[name2].prelude.call(this);
    } else {
      children = this.readSequence(this.scope.AtrulePrelude);
    }
    this.skipSC();
    if (this.eof !== true && this.tokenType !== types2.LeftCurlyBracket && this.tokenType !== types2.Semicolon) {
      this.error("Semicolon or block is expected");
    }
    return {
      type: "AtrulePrelude",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/AttributeSelector.cjs
var require_AttributeSelector = __commonJS((exports) => {
  var types2 = require_types();
  var DOLLARSIGN = 36;
  var ASTERISK = 42;
  var EQUALSSIGN = 61;
  var CIRCUMFLEXACCENT = 94;
  var VERTICALLINE = 124;
  var TILDE = 126;
  function getAttributeName() {
    if (this.eof) {
      this.error("Unexpected end of input");
    }
    const start = this.tokenStart;
    let expectIdent = false;
    if (this.isDelim(ASTERISK)) {
      expectIdent = true;
      this.next();
    } else if (!this.isDelim(VERTICALLINE)) {
      this.eat(types2.Ident);
    }
    if (this.isDelim(VERTICALLINE)) {
      if (this.charCodeAt(this.tokenStart + 1) !== EQUALSSIGN) {
        this.next();
        this.eat(types2.Ident);
      } else if (expectIdent) {
        this.error("Identifier is expected", this.tokenEnd);
      }
    } else if (expectIdent) {
      this.error("Vertical line is expected");
    }
    return {
      type: "Identifier",
      loc: this.getLocation(start, this.tokenStart),
      name: this.substrToCursor(start)
    };
  }
  function getOperator() {
    const start = this.tokenStart;
    const code = this.charCodeAt(start);
    if (code !== EQUALSSIGN && code !== TILDE && code !== CIRCUMFLEXACCENT && code !== DOLLARSIGN && code !== ASTERISK && code !== VERTICALLINE) {
      this.error("Attribute selector (=, ~=, ^=, $=, *=, |=) is expected");
    }
    this.next();
    if (code !== EQUALSSIGN) {
      if (!this.isDelim(EQUALSSIGN)) {
        this.error("Equal sign is expected");
      }
      this.next();
    }
    return this.substrToCursor(start);
  }
  var name = "AttributeSelector";
  var structure = {
    name: "Identifier",
    matcher: [String, null],
    value: ["String", "Identifier", null],
    flags: [String, null]
  };
  function parse3() {
    const start = this.tokenStart;
    let name2;
    let matcher = null;
    let value = null;
    let flags = null;
    this.eat(types2.LeftSquareBracket);
    this.skipSC();
    name2 = getAttributeName.call(this);
    this.skipSC();
    if (this.tokenType !== types2.RightSquareBracket) {
      if (this.tokenType !== types2.Ident) {
        matcher = getOperator.call(this);
        this.skipSC();
        value = this.tokenType === types2.String ? this.String() : this.Identifier();
        this.skipSC();
      }
      if (this.tokenType === types2.Ident) {
        flags = this.consume(types2.Ident);
        this.skipSC();
      }
    }
    this.eat(types2.RightSquareBracket);
    return {
      type: "AttributeSelector",
      loc: this.getLocation(start, this.tokenStart),
      name: name2,
      matcher,
      value,
      flags
    };
  }
  function generate2(node2) {
    this.token(types2.Delim, "[");
    this.node(node2.name);
    if (node2.matcher !== null) {
      this.tokenize(node2.matcher);
      this.node(node2.value);
    }
    if (node2.flags !== null) {
      this.token(types2.Ident, node2.flags);
    }
    this.token(types2.Delim, "]");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Block.cjs
var require_Block = __commonJS((exports) => {
  var types2 = require_types();
  var AMPERSAND = 38;
  function consumeRaw() {
    return this.Raw(null, true);
  }
  function consumeRule() {
    return this.parseWithFallback(this.Rule, consumeRaw);
  }
  function consumeRawDeclaration() {
    return this.Raw(this.consumeUntilSemicolonIncluded, true);
  }
  function consumeDeclaration() {
    if (this.tokenType === types2.Semicolon) {
      return consumeRawDeclaration.call(this, this.tokenIndex);
    }
    const node2 = this.parseWithFallback(this.Declaration, consumeRawDeclaration);
    if (this.tokenType === types2.Semicolon) {
      this.next();
    }
    return node2;
  }
  var name = "Block";
  var walkContext = "block";
  var structure = {
    children: [[
      "Atrule",
      "Rule",
      "Declaration"
    ]]
  };
  function parse3(isStyleBlock) {
    const consumer = isStyleBlock ? consumeDeclaration : consumeRule;
    const start = this.tokenStart;
    let children = this.createList();
    this.eat(types2.LeftCurlyBracket);
    scan:
      while (!this.eof) {
        switch (this.tokenType) {
          case types2.RightCurlyBracket:
            break scan;
          case types2.WhiteSpace:
          case types2.Comment:
            this.next();
            break;
          case types2.AtKeyword:
            children.push(this.parseWithFallback(this.Atrule.bind(this, isStyleBlock), consumeRaw));
            break;
          default:
            if (isStyleBlock && this.isDelim(AMPERSAND)) {
              children.push(consumeRule.call(this));
            } else {
              children.push(consumer.call(this));
            }
        }
      }
    if (!this.eof) {
      this.eat(types2.RightCurlyBracket);
    }
    return {
      type: "Block",
      loc: this.getLocation(start, this.tokenStart),
      children
    };
  }
  function generate2(node2) {
    this.token(types2.LeftCurlyBracket, "{");
    this.children(node2, (prev) => {
      if (prev.type === "Declaration") {
        this.token(types2.Semicolon, ";");
      }
    });
    this.token(types2.RightCurlyBracket, "}");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Brackets.cjs
var require_Brackets = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Brackets";
  var structure = {
    children: [[]]
  };
  function parse3(readSequence, recognizer) {
    const start = this.tokenStart;
    let children = null;
    this.eat(types2.LeftSquareBracket);
    children = readSequence.call(this, recognizer);
    if (!this.eof) {
      this.eat(types2.RightSquareBracket);
    }
    return {
      type: "Brackets",
      loc: this.getLocation(start, this.tokenStart),
      children
    };
  }
  function generate2(node2) {
    this.token(types2.Delim, "[");
    this.children(node2);
    this.token(types2.Delim, "]");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/CDC.cjs
var require_CDC = __commonJS((exports) => {
  var types2 = require_types();
  var name = "CDC";
  var structure = [];
  function parse3() {
    const start = this.tokenStart;
    this.eat(types2.CDC);
    return {
      type: "CDC",
      loc: this.getLocation(start, this.tokenStart)
    };
  }
  function generate2() {
    this.token(types2.CDC, "-->");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/CDO.cjs
var require_CDO = __commonJS((exports) => {
  var types2 = require_types();
  var name = "CDO";
  var structure = [];
  function parse3() {
    const start = this.tokenStart;
    this.eat(types2.CDO);
    return {
      type: "CDO",
      loc: this.getLocation(start, this.tokenStart)
    };
  }
  function generate2() {
    this.token(types2.CDO, "<!--");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/ClassSelector.cjs
var require_ClassSelector = __commonJS((exports) => {
  var types2 = require_types();
  var FULLSTOP = 46;
  var name = "ClassSelector";
  var structure = {
    name: String
  };
  function parse3() {
    this.eatDelim(FULLSTOP);
    return {
      type: "ClassSelector",
      loc: this.getLocation(this.tokenStart - 1, this.tokenEnd),
      name: this.consume(types2.Ident)
    };
  }
  function generate2(node2) {
    this.token(types2.Delim, ".");
    this.token(types2.Ident, node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Combinator.cjs
var require_Combinator = __commonJS((exports) => {
  var types2 = require_types();
  var PLUSSIGN = 43;
  var SOLIDUS = 47;
  var GREATERTHANSIGN = 62;
  var TILDE = 126;
  var name = "Combinator";
  var structure = {
    name: String
  };
  function parse3() {
    const start = this.tokenStart;
    let name2;
    switch (this.tokenType) {
      case types2.WhiteSpace:
        name2 = " ";
        break;
      case types2.Delim:
        switch (this.charCodeAt(this.tokenStart)) {
          case GREATERTHANSIGN:
          case PLUSSIGN:
          case TILDE:
            this.next();
            break;
          case SOLIDUS:
            this.next();
            this.eatIdent("deep");
            this.eatDelim(SOLIDUS);
            break;
          default:
            this.error("Combinator is expected");
        }
        name2 = this.substrToCursor(start);
        break;
    }
    return {
      type: "Combinator",
      loc: this.getLocation(start, this.tokenStart),
      name: name2
    };
  }
  function generate2(node2) {
    this.tokenize(node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Comment.cjs
var require_Comment = __commonJS((exports) => {
  var types2 = require_types();
  var ASTERISK = 42;
  var SOLIDUS = 47;
  var name = "Comment";
  var structure = {
    value: String
  };
  function parse3() {
    const start = this.tokenStart;
    let end = this.tokenEnd;
    this.eat(types2.Comment);
    if (end - start + 2 >= 2 && this.charCodeAt(end - 2) === ASTERISK && this.charCodeAt(end - 1) === SOLIDUS) {
      end -= 2;
    }
    return {
      type: "Comment",
      loc: this.getLocation(start, this.tokenStart),
      value: this.substring(start + 2, end)
    };
  }
  function generate2(node2) {
    this.token(types2.Comment, "/*" + node2.value + "*/");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Condition.cjs
var require_Condition = __commonJS((exports) => {
  var types2 = require_types();
  var likelyFeatureToken = new Set([types2.Colon, types2.RightParenthesis, types2.EOF]);
  var name = "Condition";
  var structure = {
    kind: String,
    children: [[
      "Identifier",
      "Feature",
      "FeatureFunction",
      "FeatureRange",
      "SupportsDeclaration"
    ]]
  };
  function featureOrRange(kind) {
    if (this.lookupTypeNonSC(1) === types2.Ident && likelyFeatureToken.has(this.lookupTypeNonSC(2))) {
      return this.Feature(kind);
    }
    return this.FeatureRange(kind);
  }
  var parentheses = {
    media: featureOrRange,
    container: featureOrRange,
    supports() {
      return this.SupportsDeclaration();
    }
  };
  function parse3(kind = "media") {
    const children = this.createList();
    scan:
      while (!this.eof) {
        switch (this.tokenType) {
          case types2.Comment:
          case types2.WhiteSpace:
            this.next();
            continue;
          case types2.Ident:
            children.push(this.Identifier());
            break;
          case types2.LeftParenthesis: {
            let term = this.parseWithFallback(() => parentheses[kind].call(this, kind), () => null);
            if (!term) {
              term = this.parseWithFallback(() => {
                this.eat(types2.LeftParenthesis);
                const res = this.Condition(kind);
                this.eat(types2.RightParenthesis);
                return res;
              }, () => {
                return this.GeneralEnclosed(kind);
              });
            }
            children.push(term);
            break;
          }
          case types2.Function: {
            let term = this.parseWithFallback(() => this.FeatureFunction(kind), () => null);
            if (!term) {
              term = this.GeneralEnclosed(kind);
            }
            children.push(term);
            break;
          }
          default:
            break scan;
        }
      }
    if (children.isEmpty) {
      this.error("Condition is expected");
    }
    return {
      type: "Condition",
      loc: this.getLocationFromList(children),
      kind,
      children
    };
  }
  function generate2(node2) {
    node2.children.forEach((child) => {
      if (child.type === "Condition") {
        this.token(types2.LeftParenthesis, "(");
        this.node(child);
        this.token(types2.RightParenthesis, ")");
      } else {
        this.node(child);
      }
    });
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Declaration.cjs
var require_Declaration = __commonJS((exports) => {
  var names = require_names2();
  var types2 = require_types();
  var EXCLAMATIONMARK = 33;
  var NUMBERSIGN = 35;
  var DOLLARSIGN = 36;
  var AMPERSAND = 38;
  var ASTERISK = 42;
  var PLUSSIGN = 43;
  var SOLIDUS = 47;
  function consumeValueRaw() {
    return this.Raw(this.consumeUntilExclamationMarkOrSemicolon, true);
  }
  function consumeCustomPropertyRaw() {
    return this.Raw(this.consumeUntilExclamationMarkOrSemicolon, false);
  }
  function consumeValue() {
    const startValueToken = this.tokenIndex;
    const value = this.Value();
    if (value.type !== "Raw" && this.eof === false && this.tokenType !== types2.Semicolon && this.isDelim(EXCLAMATIONMARK) === false && this.isBalanceEdge(startValueToken) === false) {
      this.error();
    }
    return value;
  }
  var name = "Declaration";
  var walkContext = "declaration";
  var structure = {
    important: [Boolean, String],
    property: String,
    value: ["Value", "Raw"]
  };
  function parse3() {
    const start = this.tokenStart;
    const startToken = this.tokenIndex;
    const property = readProperty.call(this);
    const customProperty = names.isCustomProperty(property);
    const parseValue = customProperty ? this.parseCustomProperty : this.parseValue;
    const consumeRaw = customProperty ? consumeCustomPropertyRaw : consumeValueRaw;
    let important = false;
    let value;
    this.skipSC();
    this.eat(types2.Colon);
    const valueStart = this.tokenIndex;
    if (!customProperty) {
      this.skipSC();
    }
    if (parseValue) {
      value = this.parseWithFallback(consumeValue, consumeRaw);
    } else {
      value = consumeRaw.call(this, this.tokenIndex);
    }
    if (customProperty && value.type === "Value" && value.children.isEmpty) {
      for (let offset = valueStart - this.tokenIndex;offset <= 0; offset++) {
        if (this.lookupType(offset) === types2.WhiteSpace) {
          value.children.appendData({
            type: "WhiteSpace",
            loc: null,
            value: " "
          });
          break;
        }
      }
    }
    if (this.isDelim(EXCLAMATIONMARK)) {
      important = getImportant.call(this);
      this.skipSC();
    }
    if (this.eof === false && this.tokenType !== types2.Semicolon && this.isBalanceEdge(startToken) === false) {
      this.error();
    }
    return {
      type: "Declaration",
      loc: this.getLocation(start, this.tokenStart),
      important,
      property,
      value
    };
  }
  function generate2(node2) {
    this.token(types2.Ident, node2.property);
    this.token(types2.Colon, ":");
    this.node(node2.value);
    if (node2.important) {
      this.token(types2.Delim, "!");
      this.token(types2.Ident, node2.important === true ? "important" : node2.important);
    }
  }
  function readProperty() {
    const start = this.tokenStart;
    if (this.tokenType === types2.Delim) {
      switch (this.charCodeAt(this.tokenStart)) {
        case ASTERISK:
        case DOLLARSIGN:
        case PLUSSIGN:
        case NUMBERSIGN:
        case AMPERSAND:
          this.next();
          break;
        case SOLIDUS:
          this.next();
          if (this.isDelim(SOLIDUS)) {
            this.next();
          }
          break;
      }
    }
    if (this.tokenType === types2.Hash) {
      this.eat(types2.Hash);
    } else {
      this.eat(types2.Ident);
    }
    return this.substrToCursor(start);
  }
  function getImportant() {
    this.eat(types2.Delim);
    this.skipSC();
    const important = this.consume(types2.Ident);
    return important === "important" ? true : important;
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/DeclarationList.cjs
var require_DeclarationList = __commonJS((exports) => {
  var types2 = require_types();
  var AMPERSAND = 38;
  function consumeRaw() {
    return this.Raw(this.consumeUntilSemicolonIncluded, true);
  }
  var name = "DeclarationList";
  var structure = {
    children: [[
      "Declaration",
      "Atrule",
      "Rule"
    ]]
  };
  function parse3() {
    const children = this.createList();
    while (!this.eof) {
      switch (this.tokenType) {
        case types2.WhiteSpace:
        case types2.Comment:
        case types2.Semicolon:
          this.next();
          break;
        case types2.AtKeyword:
          children.push(this.parseWithFallback(this.Atrule.bind(this, true), consumeRaw));
          break;
        default:
          if (this.isDelim(AMPERSAND)) {
            children.push(this.parseWithFallback(this.Rule, consumeRaw));
          } else {
            children.push(this.parseWithFallback(this.Declaration, consumeRaw));
          }
      }
    }
    return {
      type: "DeclarationList",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2, (prev) => {
      if (prev.type === "Declaration") {
        this.token(types2.Semicolon, ";");
      }
    });
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Dimension.cjs
var require_Dimension = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Dimension";
  var structure = {
    value: String,
    unit: String
  };
  function parse3() {
    const start = this.tokenStart;
    const value = this.consumeNumber(types2.Dimension);
    return {
      type: "Dimension",
      loc: this.getLocation(start, this.tokenStart),
      value,
      unit: this.substring(start + value.length, this.tokenStart)
    };
  }
  function generate2(node2) {
    this.token(types2.Dimension, node2.value + node2.unit);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Feature.cjs
var require_Feature = __commonJS((exports) => {
  var types2 = require_types();
  var SOLIDUS = 47;
  var name = "Feature";
  var structure = {
    kind: String,
    name: String,
    value: ["Identifier", "Number", "Dimension", "Ratio", "Function", null]
  };
  function parse3(kind) {
    const start = this.tokenStart;
    let name2;
    let value = null;
    this.eat(types2.LeftParenthesis);
    this.skipSC();
    name2 = this.consume(types2.Ident);
    this.skipSC();
    if (this.tokenType !== types2.RightParenthesis) {
      this.eat(types2.Colon);
      this.skipSC();
      switch (this.tokenType) {
        case types2.Number:
          if (this.lookupNonWSType(1) === types2.Delim) {
            value = this.Ratio();
          } else {
            value = this.Number();
          }
          break;
        case types2.Dimension:
          value = this.Dimension();
          break;
        case types2.Ident:
          value = this.Identifier();
          break;
        case types2.Function:
          value = this.parseWithFallback(() => {
            const res = this.Function(this.readSequence, this.scope.Value);
            this.skipSC();
            if (this.isDelim(SOLIDUS)) {
              this.error();
            }
            return res;
          }, () => {
            return this.Ratio();
          });
          break;
        default:
          this.error("Number, dimension, ratio or identifier is expected");
      }
      this.skipSC();
    }
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "Feature",
      loc: this.getLocation(start, this.tokenStart),
      kind,
      name: name2,
      value
    };
  }
  function generate2(node2) {
    this.token(types2.LeftParenthesis, "(");
    this.token(types2.Ident, node2.name);
    if (node2.value !== null) {
      this.token(types2.Colon, ":");
      this.node(node2.value);
    }
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/FeatureFunction.cjs
var require_FeatureFunction = __commonJS((exports) => {
  var types2 = require_types();
  var name = "FeatureFunction";
  var structure = {
    kind: String,
    feature: String,
    value: ["Declaration", "Selector"]
  };
  function getFeatureParser(kind, name2) {
    const featuresOfKind = this.features[kind] || {};
    const parser = featuresOfKind[name2];
    if (typeof parser !== "function") {
      this.error(`Unknown feature ${name2}()`);
    }
    return parser;
  }
  function parse3(kind = "unknown") {
    const start = this.tokenStart;
    const functionName = this.consumeFunctionName();
    const valueParser = getFeatureParser.call(this, kind, functionName.toLowerCase());
    this.skipSC();
    const value = this.parseWithFallback(() => {
      const startValueToken = this.tokenIndex;
      const value2 = valueParser.call(this);
      if (this.eof === false && this.isBalanceEdge(startValueToken) === false) {
        this.error();
      }
      return value2;
    }, () => this.Raw(null, false));
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "FeatureFunction",
      loc: this.getLocation(start, this.tokenStart),
      kind,
      feature: functionName,
      value
    };
  }
  function generate2(node2) {
    this.token(types2.Function, node2.feature + "(");
    this.node(node2.value);
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/FeatureRange.cjs
var require_FeatureRange = __commonJS((exports) => {
  var types2 = require_types();
  var SOLIDUS = 47;
  var LESSTHANSIGN = 60;
  var EQUALSSIGN = 61;
  var GREATERTHANSIGN = 62;
  var name = "FeatureRange";
  var structure = {
    kind: String,
    left: ["Identifier", "Number", "Dimension", "Ratio", "Function"],
    leftComparison: String,
    middle: ["Identifier", "Number", "Dimension", "Ratio", "Function"],
    rightComparison: [String, null],
    right: ["Identifier", "Number", "Dimension", "Ratio", "Function", null]
  };
  function readTerm() {
    this.skipSC();
    switch (this.tokenType) {
      case types2.Number:
        if (this.isDelim(SOLIDUS, this.lookupOffsetNonSC(1))) {
          return this.Ratio();
        } else {
          return this.Number();
        }
      case types2.Dimension:
        return this.Dimension();
      case types2.Ident:
        return this.Identifier();
      case types2.Function:
        return this.parseWithFallback(() => {
          const res = this.Function(this.readSequence, this.scope.Value);
          this.skipSC();
          if (this.isDelim(SOLIDUS)) {
            this.error();
          }
          return res;
        }, () => {
          return this.Ratio();
        });
      default:
        this.error("Number, dimension, ratio or identifier is expected");
    }
  }
  function readComparison(expectColon) {
    this.skipSC();
    if (this.isDelim(LESSTHANSIGN) || this.isDelim(GREATERTHANSIGN)) {
      const value = this.source[this.tokenStart];
      this.next();
      if (this.isDelim(EQUALSSIGN)) {
        this.next();
        return value + "=";
      }
      return value;
    }
    if (this.isDelim(EQUALSSIGN)) {
      return "=";
    }
    this.error(`Expected ${expectColon ? '":", ' : ""}"<", ">", "=" or ")"`);
  }
  function parse3(kind = "unknown") {
    const start = this.tokenStart;
    this.skipSC();
    this.eat(types2.LeftParenthesis);
    const left = readTerm.call(this);
    const leftComparison = readComparison.call(this, left.type === "Identifier");
    const middle = readTerm.call(this);
    let rightComparison = null;
    let right = null;
    if (this.lookupNonWSType(0) !== types2.RightParenthesis) {
      rightComparison = readComparison.call(this);
      right = readTerm.call(this);
    }
    this.skipSC();
    this.eat(types2.RightParenthesis);
    return {
      type: "FeatureRange",
      loc: this.getLocation(start, this.tokenStart),
      kind,
      left,
      leftComparison,
      middle,
      rightComparison,
      right
    };
  }
  function generate2(node2) {
    this.token(types2.LeftParenthesis, "(");
    this.node(node2.left);
    this.tokenize(node2.leftComparison);
    this.node(node2.middle);
    if (node2.right) {
      this.tokenize(node2.rightComparison);
      this.node(node2.right);
    }
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Function.cjs
var require_Function = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Function";
  var walkContext = "function";
  var structure = {
    name: String,
    children: [[]]
  };
  function parse3(readSequence, recognizer) {
    const start = this.tokenStart;
    const name2 = this.consumeFunctionName();
    const nameLowerCase = name2.toLowerCase();
    let children;
    children = recognizer.hasOwnProperty(nameLowerCase) ? recognizer[nameLowerCase].call(this, recognizer) : readSequence.call(this, recognizer);
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "Function",
      loc: this.getLocation(start, this.tokenStart),
      name: name2,
      children
    };
  }
  function generate2(node2) {
    this.token(types2.Function, node2.name + "(");
    this.children(node2);
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/GeneralEnclosed.cjs
var require_GeneralEnclosed = __commonJS((exports) => {
  var types2 = require_types();
  var name = "GeneralEnclosed";
  var structure = {
    kind: String,
    function: [String, null],
    children: [[]]
  };
  function parse3(kind) {
    const start = this.tokenStart;
    let functionName = null;
    if (this.tokenType === types2.Function) {
      functionName = this.consumeFunctionName();
    } else {
      this.eat(types2.LeftParenthesis);
    }
    const children = this.parseWithFallback(() => {
      const startValueToken = this.tokenIndex;
      const children2 = this.readSequence(this.scope.Value);
      if (this.eof === false && this.isBalanceEdge(startValueToken) === false) {
        this.error();
      }
      return children2;
    }, () => this.createSingleNodeList(this.Raw(null, false)));
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "GeneralEnclosed",
      loc: this.getLocation(start, this.tokenStart),
      kind,
      function: functionName,
      children
    };
  }
  function generate2(node2) {
    if (node2.function) {
      this.token(types2.Function, node2.function + "(");
    } else {
      this.token(types2.LeftParenthesis, "(");
    }
    this.children(node2);
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Hash.cjs
var require_Hash = __commonJS((exports) => {
  var types2 = require_types();
  var xxx = "XXX";
  var name = "Hash";
  var structure = {
    value: String
  };
  function parse3() {
    const start = this.tokenStart;
    this.eat(types2.Hash);
    return {
      type: "Hash",
      loc: this.getLocation(start, this.tokenStart),
      value: this.substrToCursor(start + 1)
    };
  }
  function generate2(node2) {
    this.token(types2.Hash, "#" + node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.xxx = xxx;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Identifier.cjs
var require_Identifier = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Identifier";
  var structure = {
    name: String
  };
  function parse3() {
    return {
      type: "Identifier",
      loc: this.getLocation(this.tokenStart, this.tokenEnd),
      name: this.consume(types2.Ident)
    };
  }
  function generate2(node2) {
    this.token(types2.Ident, node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/IdSelector.cjs
var require_IdSelector = __commonJS((exports) => {
  var types2 = require_types();
  var name = "IdSelector";
  var structure = {
    name: String
  };
  function parse3() {
    const start = this.tokenStart;
    this.eat(types2.Hash);
    return {
      type: "IdSelector",
      loc: this.getLocation(start, this.tokenStart),
      name: this.substrToCursor(start + 1)
    };
  }
  function generate2(node2) {
    this.token(types2.Delim, "#" + node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Layer.cjs
var require_Layer = __commonJS((exports) => {
  var types2 = require_types();
  var FULLSTOP = 46;
  var name = "Layer";
  var structure = {
    name: String
  };
  function parse3() {
    let tokenStart = this.tokenStart;
    let name2 = this.consume(types2.Ident);
    while (this.isDelim(FULLSTOP)) {
      this.eat(types2.Delim);
      name2 += "." + this.consume(types2.Ident);
    }
    return {
      type: "Layer",
      loc: this.getLocation(tokenStart, this.tokenStart),
      name: name2
    };
  }
  function generate2(node2) {
    this.tokenize(node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/LayerList.cjs
var require_LayerList = __commonJS((exports) => {
  var types2 = require_types();
  var name = "LayerList";
  var structure = {
    children: [[
      "Layer"
    ]]
  };
  function parse3() {
    const children = this.createList();
    this.skipSC();
    while (!this.eof) {
      children.push(this.Layer());
      if (this.lookupTypeNonSC(0) !== types2.Comma) {
        break;
      }
      this.skipSC();
      this.next();
      this.skipSC();
    }
    return {
      type: "LayerList",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2, () => this.token(types2.Comma, ","));
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/MediaQuery.cjs
var require_MediaQuery = __commonJS((exports) => {
  var types2 = require_types();
  var name = "MediaQuery";
  var structure = {
    modifier: [String, null],
    mediaType: [String, null],
    condition: ["Condition", null]
  };
  function parse3() {
    const start = this.tokenStart;
    let modifier = null;
    let mediaType = null;
    let condition = null;
    this.skipSC();
    if (this.tokenType === types2.Ident && this.lookupTypeNonSC(1) !== types2.LeftParenthesis) {
      const ident = this.consume(types2.Ident);
      const identLowerCase = ident.toLowerCase();
      if (identLowerCase === "not" || identLowerCase === "only") {
        this.skipSC();
        modifier = identLowerCase;
        mediaType = this.consume(types2.Ident);
      } else {
        mediaType = ident;
      }
      switch (this.lookupTypeNonSC(0)) {
        case types2.Ident: {
          this.skipSC();
          this.eatIdent("and");
          condition = this.Condition("media");
          break;
        }
        case types2.LeftCurlyBracket:
        case types2.Semicolon:
        case types2.Comma:
        case types2.EOF:
          break;
        default:
          this.error("Identifier or parenthesis is expected");
      }
    } else {
      switch (this.tokenType) {
        case types2.Ident:
        case types2.LeftParenthesis:
        case types2.Function: {
          condition = this.Condition("media");
          break;
        }
        case types2.LeftCurlyBracket:
        case types2.Semicolon:
        case types2.EOF:
          break;
        default:
          this.error("Identifier or parenthesis is expected");
      }
    }
    return {
      type: "MediaQuery",
      loc: this.getLocation(start, this.tokenStart),
      modifier,
      mediaType,
      condition
    };
  }
  function generate2(node2) {
    if (node2.mediaType) {
      if (node2.modifier) {
        this.token(types2.Ident, node2.modifier);
      }
      this.token(types2.Ident, node2.mediaType);
      if (node2.condition) {
        this.token(types2.Ident, "and");
        this.node(node2.condition);
      }
    } else if (node2.condition) {
      this.node(node2.condition);
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/MediaQueryList.cjs
var require_MediaQueryList = __commonJS((exports) => {
  var types2 = require_types();
  var name = "MediaQueryList";
  var structure = {
    children: [[
      "MediaQuery"
    ]]
  };
  function parse3() {
    const children = this.createList();
    this.skipSC();
    while (!this.eof) {
      children.push(this.MediaQuery());
      if (this.tokenType !== types2.Comma) {
        break;
      }
      this.next();
    }
    return {
      type: "MediaQueryList",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2, () => this.token(types2.Comma, ","));
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/NestingSelector.cjs
var require_NestingSelector = __commonJS((exports) => {
  var types2 = require_types();
  var AMPERSAND = 38;
  var name = "NestingSelector";
  var structure = {};
  function parse3() {
    const start = this.tokenStart;
    this.eatDelim(AMPERSAND);
    return {
      type: "NestingSelector",
      loc: this.getLocation(start, this.tokenStart)
    };
  }
  function generate2() {
    this.token(types2.Delim, "&");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Nth.cjs
var require_Nth = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Nth";
  var structure = {
    nth: ["AnPlusB", "Identifier"],
    selector: ["SelectorList", null]
  };
  function parse3() {
    this.skipSC();
    const start = this.tokenStart;
    let end = start;
    let selector = null;
    let nth;
    if (this.lookupValue(0, "odd") || this.lookupValue(0, "even")) {
      nth = this.Identifier();
    } else {
      nth = this.AnPlusB();
    }
    end = this.tokenStart;
    this.skipSC();
    if (this.lookupValue(0, "of")) {
      this.next();
      selector = this.SelectorList();
      end = this.tokenStart;
    }
    return {
      type: "Nth",
      loc: this.getLocation(start, end),
      nth,
      selector
    };
  }
  function generate2(node2) {
    this.node(node2.nth);
    if (node2.selector !== null) {
      this.token(types2.Ident, "of");
      this.node(node2.selector);
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Number.cjs
var require_Number = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Number";
  var structure = {
    value: String
  };
  function parse3() {
    return {
      type: "Number",
      loc: this.getLocation(this.tokenStart, this.tokenEnd),
      value: this.consume(types2.Number)
    };
  }
  function generate2(node2) {
    this.token(types2.Number, node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Operator.cjs
var require_Operator = __commonJS((exports) => {
  var name = "Operator";
  var structure = {
    value: String
  };
  function parse3() {
    const start = this.tokenStart;
    this.next();
    return {
      type: "Operator",
      loc: this.getLocation(start, this.tokenStart),
      value: this.substrToCursor(start)
    };
  }
  function generate2(node2) {
    this.tokenize(node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Parentheses.cjs
var require_Parentheses = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Parentheses";
  var structure = {
    children: [[]]
  };
  function parse3(readSequence, recognizer) {
    const start = this.tokenStart;
    let children = null;
    this.eat(types2.LeftParenthesis);
    children = readSequence.call(this, recognizer);
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "Parentheses",
      loc: this.getLocation(start, this.tokenStart),
      children
    };
  }
  function generate2(node2) {
    this.token(types2.LeftParenthesis, "(");
    this.children(node2);
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Percentage.cjs
var require_Percentage = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Percentage";
  var structure = {
    value: String
  };
  function parse3() {
    return {
      type: "Percentage",
      loc: this.getLocation(this.tokenStart, this.tokenEnd),
      value: this.consumeNumber(types2.Percentage)
    };
  }
  function generate2(node2) {
    this.token(types2.Percentage, node2.value + "%");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/PseudoClassSelector.cjs
var require_PseudoClassSelector = __commonJS((exports) => {
  var types2 = require_types();
  var name = "PseudoClassSelector";
  var walkContext = "function";
  var structure = {
    name: String,
    children: [["Raw"], null]
  };
  function parse3() {
    const start = this.tokenStart;
    let children = null;
    let name2;
    let nameLowerCase;
    this.eat(types2.Colon);
    if (this.tokenType === types2.Function) {
      name2 = this.consumeFunctionName();
      nameLowerCase = name2.toLowerCase();
      if (this.lookupNonWSType(0) == types2.RightParenthesis) {
        children = this.createList();
      } else if (hasOwnProperty.call(this.pseudo, nameLowerCase)) {
        this.skipSC();
        children = this.pseudo[nameLowerCase].call(this);
        this.skipSC();
      } else {
        children = this.createList();
        children.push(this.Raw(null, false));
      }
      this.eat(types2.RightParenthesis);
    } else {
      name2 = this.consume(types2.Ident);
    }
    return {
      type: "PseudoClassSelector",
      loc: this.getLocation(start, this.tokenStart),
      name: name2,
      children
    };
  }
  function generate2(node2) {
    this.token(types2.Colon, ":");
    if (node2.children === null) {
      this.token(types2.Ident, node2.name);
    } else {
      this.token(types2.Function, node2.name + "(");
      this.children(node2);
      this.token(types2.RightParenthesis, ")");
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/PseudoElementSelector.cjs
var require_PseudoElementSelector = __commonJS((exports) => {
  var types2 = require_types();
  var name = "PseudoElementSelector";
  var walkContext = "function";
  var structure = {
    name: String,
    children: [["Raw"], null]
  };
  function parse3() {
    const start = this.tokenStart;
    let children = null;
    let name2;
    let nameLowerCase;
    this.eat(types2.Colon);
    this.eat(types2.Colon);
    if (this.tokenType === types2.Function) {
      name2 = this.consumeFunctionName();
      nameLowerCase = name2.toLowerCase();
      if (this.lookupNonWSType(0) == types2.RightParenthesis) {
        children = this.createList();
      } else if (hasOwnProperty.call(this.pseudo, nameLowerCase)) {
        this.skipSC();
        children = this.pseudo[nameLowerCase].call(this);
        this.skipSC();
      } else {
        children = this.createList();
        children.push(this.Raw(null, false));
      }
      this.eat(types2.RightParenthesis);
    } else {
      name2 = this.consume(types2.Ident);
    }
    return {
      type: "PseudoElementSelector",
      loc: this.getLocation(start, this.tokenStart),
      name: name2,
      children
    };
  }
  function generate2(node2) {
    this.token(types2.Colon, ":");
    this.token(types2.Colon, ":");
    if (node2.children === null) {
      this.token(types2.Ident, node2.name);
    } else {
      this.token(types2.Function, node2.name + "(");
      this.children(node2);
      this.token(types2.RightParenthesis, ")");
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Ratio.cjs
var require_Ratio = __commonJS((exports) => {
  var types2 = require_types();
  var SOLIDUS = 47;
  function consumeTerm() {
    this.skipSC();
    switch (this.tokenType) {
      case types2.Number:
        return this.Number();
      case types2.Function:
        return this.Function(this.readSequence, this.scope.Value);
      default:
        this.error("Number of function is expected");
    }
  }
  var name = "Ratio";
  var structure = {
    left: ["Number", "Function"],
    right: ["Number", "Function", null]
  };
  function parse3() {
    const start = this.tokenStart;
    const left = consumeTerm.call(this);
    let right = null;
    this.skipSC();
    if (this.isDelim(SOLIDUS)) {
      this.eatDelim(SOLIDUS);
      right = consumeTerm.call(this);
    }
    return {
      type: "Ratio",
      loc: this.getLocation(start, this.tokenStart),
      left,
      right
    };
  }
  function generate2(node2) {
    this.node(node2.left);
    this.token(types2.Delim, "/");
    if (node2.right) {
      this.node(node2.right);
    } else {
      this.node(types2.Number, 1);
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Raw.cjs
var require_Raw = __commonJS((exports) => {
  var types2 = require_types();
  function getOffsetExcludeWS() {
    if (this.tokenIndex > 0) {
      if (this.lookupType(-1) === types2.WhiteSpace) {
        return this.tokenIndex > 1 ? this.getTokenStart(this.tokenIndex - 1) : this.firstCharOffset;
      }
    }
    return this.tokenStart;
  }
  var name = "Raw";
  var structure = {
    value: String
  };
  function parse3(consumeUntil, excludeWhiteSpace) {
    const startOffset = this.getTokenStart(this.tokenIndex);
    let endOffset;
    this.skipUntilBalanced(this.tokenIndex, consumeUntil || this.consumeUntilBalanceEnd);
    if (excludeWhiteSpace && this.tokenStart > startOffset) {
      endOffset = getOffsetExcludeWS.call(this);
    } else {
      endOffset = this.tokenStart;
    }
    return {
      type: "Raw",
      loc: this.getLocation(startOffset, endOffset),
      value: this.substring(startOffset, endOffset)
    };
  }
  function generate2(node2) {
    this.tokenize(node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Rule.cjs
var require_Rule = __commonJS((exports) => {
  var types2 = require_types();
  function consumeRaw() {
    return this.Raw(this.consumeUntilLeftCurlyBracket, true);
  }
  function consumePrelude() {
    const prelude = this.SelectorList();
    if (prelude.type !== "Raw" && this.eof === false && this.tokenType !== types2.LeftCurlyBracket) {
      this.error();
    }
    return prelude;
  }
  var name = "Rule";
  var walkContext = "rule";
  var structure = {
    prelude: ["SelectorList", "Raw"],
    block: ["Block"]
  };
  function parse3() {
    const startToken = this.tokenIndex;
    const startOffset = this.tokenStart;
    let prelude;
    let block;
    if (this.parseRulePrelude) {
      prelude = this.parseWithFallback(consumePrelude, consumeRaw);
    } else {
      prelude = consumeRaw.call(this, startToken);
    }
    block = this.Block(true);
    return {
      type: "Rule",
      loc: this.getLocation(startOffset, this.tokenStart),
      prelude,
      block
    };
  }
  function generate2(node2) {
    this.node(node2.prelude);
    this.node(node2.block);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Scope.cjs
var require_Scope = __commonJS((exports) => {
  var types2 = require_types();
  var name = "Scope";
  var structure = {
    root: ["SelectorList", "Raw", null],
    limit: ["SelectorList", "Raw", null]
  };
  function parse3() {
    let root = null;
    let limit = null;
    this.skipSC();
    const startOffset = this.tokenStart;
    if (this.tokenType === types2.LeftParenthesis) {
      this.next();
      this.skipSC();
      root = this.parseWithFallback(this.SelectorList, () => this.Raw(false, true));
      this.skipSC();
      this.eat(types2.RightParenthesis);
    }
    if (this.lookupNonWSType(0) === types2.Ident) {
      this.skipSC();
      this.eatIdent("to");
      this.skipSC();
      this.eat(types2.LeftParenthesis);
      this.skipSC();
      limit = this.parseWithFallback(this.SelectorList, () => this.Raw(false, true));
      this.skipSC();
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "Scope",
      loc: this.getLocation(startOffset, this.tokenStart),
      root,
      limit
    };
  }
  function generate2(node2) {
    if (node2.root) {
      this.token(types2.LeftParenthesis, "(");
      this.node(node2.root);
      this.token(types2.RightParenthesis, ")");
    }
    if (node2.limit) {
      this.token(types2.Ident, "to");
      this.token(types2.LeftParenthesis, "(");
      this.node(node2.limit);
      this.token(types2.RightParenthesis, ")");
    }
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Selector.cjs
var require_Selector = __commonJS((exports) => {
  var name = "Selector";
  var structure = {
    children: [[
      "TypeSelector",
      "IdSelector",
      "ClassSelector",
      "AttributeSelector",
      "PseudoClassSelector",
      "PseudoElementSelector",
      "Combinator"
    ]]
  };
  function parse3() {
    const children = this.readSequence(this.scope.Selector);
    if (this.getFirstListNode(children) === null) {
      this.error("Selector is expected");
    }
    return {
      type: "Selector",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/SelectorList.cjs
var require_SelectorList = __commonJS((exports) => {
  var types2 = require_types();
  var name = "SelectorList";
  var walkContext = "selector";
  var structure = {
    children: [[
      "Selector",
      "Raw"
    ]]
  };
  function parse3() {
    const children = this.createList();
    while (!this.eof) {
      children.push(this.Selector());
      if (this.tokenType === types2.Comma) {
        this.next();
        continue;
      }
      break;
    }
    return {
      type: "SelectorList",
      loc: this.getLocationFromList(children),
      children
    };
  }
  function generate2(node2) {
    this.children(node2, () => this.token(types2.Comma, ","));
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/string.cjs
var require_string = __commonJS((exports) => {
  var charCodeDefinitions = require_char_code_definitions();
  var utils = require_utils();
  var REVERSE_SOLIDUS = 92;
  var QUOTATION_MARK = 34;
  var APOSTROPHE = 39;
  function decode(str) {
    const len = str.length;
    const firstChar = str.charCodeAt(0);
    const start = firstChar === QUOTATION_MARK || firstChar === APOSTROPHE ? 1 : 0;
    const end = start === 1 && len > 1 && str.charCodeAt(len - 1) === firstChar ? len - 2 : len - 1;
    let decoded = "";
    for (let i = start;i <= end; i++) {
      let code = str.charCodeAt(i);
      if (code === REVERSE_SOLIDUS) {
        if (i === end) {
          if (i !== len - 1) {
            decoded = str.substr(i + 1);
          }
          break;
        }
        code = str.charCodeAt(++i);
        if (charCodeDefinitions.isValidEscape(REVERSE_SOLIDUS, code)) {
          const escapeStart = i - 1;
          const escapeEnd = utils.consumeEscaped(str, escapeStart);
          i = escapeEnd - 1;
          decoded += utils.decodeEscaped(str.substring(escapeStart + 1, escapeEnd));
        } else {
          if (code === 13 && str.charCodeAt(i + 1) === 10) {
            i++;
          }
        }
      } else {
        decoded += str[i];
      }
    }
    return decoded;
  }
  function encode(str, apostrophe) {
    const quote = apostrophe ? "'" : '"';
    const quoteCode = apostrophe ? APOSTROPHE : QUOTATION_MARK;
    let encoded = "";
    let wsBeforeHexIsNeeded = false;
    for (let i = 0;i < str.length; i++) {
      const code = str.charCodeAt(i);
      if (code === 0) {
        encoded += "�";
        continue;
      }
      if (code <= 31 || code === 127) {
        encoded += "\\" + code.toString(16);
        wsBeforeHexIsNeeded = true;
        continue;
      }
      if (code === quoteCode || code === REVERSE_SOLIDUS) {
        encoded += "\\" + str.charAt(i);
        wsBeforeHexIsNeeded = false;
      } else {
        if (wsBeforeHexIsNeeded && (charCodeDefinitions.isHexDigit(code) || charCodeDefinitions.isWhiteSpace(code))) {
          encoded += " ";
        }
        encoded += str.charAt(i);
        wsBeforeHexIsNeeded = false;
      }
    }
    return quote + encoded + quote;
  }
  exports.decode = decode;
  exports.encode = encode;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/String.cjs
var require_String = __commonJS((exports) => {
  var string = require_string();
  var types2 = require_types();
  var name = "String";
  var structure = {
    value: String
  };
  function parse3() {
    return {
      type: "String",
      loc: this.getLocation(this.tokenStart, this.tokenEnd),
      value: string.decode(this.consume(types2.String))
    };
  }
  function generate2(node2) {
    this.token(types2.String, string.encode(node2.value));
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/StyleSheet.cjs
var require_StyleSheet = __commonJS((exports) => {
  var types2 = require_types();
  var EXCLAMATIONMARK = 33;
  function consumeRaw() {
    return this.Raw(null, false);
  }
  var name = "StyleSheet";
  var walkContext = "stylesheet";
  var structure = {
    children: [[
      "Comment",
      "CDO",
      "CDC",
      "Atrule",
      "Rule",
      "Raw"
    ]]
  };
  function parse3() {
    const start = this.tokenStart;
    const children = this.createList();
    let child;
    while (!this.eof) {
      switch (this.tokenType) {
        case types2.WhiteSpace:
          this.next();
          continue;
        case types2.Comment:
          if (this.charCodeAt(this.tokenStart + 2) !== EXCLAMATIONMARK) {
            this.next();
            continue;
          }
          child = this.Comment();
          break;
        case types2.CDO:
          child = this.CDO();
          break;
        case types2.CDC:
          child = this.CDC();
          break;
        case types2.AtKeyword:
          child = this.parseWithFallback(this.Atrule, consumeRaw);
          break;
        default:
          child = this.parseWithFallback(this.Rule, consumeRaw);
      }
      children.push(child);
    }
    return {
      type: "StyleSheet",
      loc: this.getLocation(start, this.tokenStart),
      children
    };
  }
  function generate2(node2) {
    this.children(node2);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
  exports.walkContext = walkContext;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/SupportsDeclaration.cjs
var require_SupportsDeclaration = __commonJS((exports) => {
  var types2 = require_types();
  var name = "SupportsDeclaration";
  var structure = {
    declaration: "Declaration"
  };
  function parse3() {
    const start = this.tokenStart;
    this.eat(types2.LeftParenthesis);
    this.skipSC();
    const declaration = this.Declaration();
    if (!this.eof) {
      this.eat(types2.RightParenthesis);
    }
    return {
      type: "SupportsDeclaration",
      loc: this.getLocation(start, this.tokenStart),
      declaration
    };
  }
  function generate2(node2) {
    this.token(types2.LeftParenthesis, "(");
    this.node(node2.declaration);
    this.token(types2.RightParenthesis, ")");
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/TypeSelector.cjs
var require_TypeSelector = __commonJS((exports) => {
  var types2 = require_types();
  var ASTERISK = 42;
  var VERTICALLINE = 124;
  function eatIdentifierOrAsterisk() {
    if (this.tokenType !== types2.Ident && this.isDelim(ASTERISK) === false) {
      this.error("Identifier or asterisk is expected");
    }
    this.next();
  }
  var name = "TypeSelector";
  var structure = {
    name: String
  };
  function parse3() {
    const start = this.tokenStart;
    if (this.isDelim(VERTICALLINE)) {
      this.next();
      eatIdentifierOrAsterisk.call(this);
    } else {
      eatIdentifierOrAsterisk.call(this);
      if (this.isDelim(VERTICALLINE)) {
        this.next();
        eatIdentifierOrAsterisk.call(this);
      }
    }
    return {
      type: "TypeSelector",
      loc: this.getLocation(start, this.tokenStart),
      name: this.substrToCursor(start)
    };
  }
  function generate2(node2) {
    this.tokenize(node2.name);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/UnicodeRange.cjs
var require_UnicodeRange = __commonJS((exports) => {
  var types2 = require_types();
  var charCodeDefinitions = require_char_code_definitions();
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var QUESTIONMARK = 63;
  function eatHexSequence(offset, allowDash) {
    let len = 0;
    for (let pos = this.tokenStart + offset;pos < this.tokenEnd; pos++) {
      const code = this.charCodeAt(pos);
      if (code === HYPHENMINUS && allowDash && len !== 0) {
        eatHexSequence.call(this, offset + len + 1, false);
        return -1;
      }
      if (!charCodeDefinitions.isHexDigit(code)) {
        this.error(allowDash && len !== 0 ? "Hyphen minus" + (len < 6 ? " or hex digit" : "") + " is expected" : len < 6 ? "Hex digit is expected" : "Unexpected input", pos);
      }
      if (++len > 6) {
        this.error("Too many hex digits", pos);
      }
    }
    this.next();
    return len;
  }
  function eatQuestionMarkSequence(max) {
    let count = 0;
    while (this.isDelim(QUESTIONMARK)) {
      if (++count > max) {
        this.error("Too many question marks");
      }
      this.next();
    }
  }
  function startsWith(code) {
    if (this.charCodeAt(this.tokenStart) !== code) {
      this.error((code === PLUSSIGN ? "Plus sign" : "Hyphen minus") + " is expected");
    }
  }
  function scanUnicodeRange() {
    let hexLength = 0;
    switch (this.tokenType) {
      case types2.Number:
        hexLength = eatHexSequence.call(this, 1, true);
        if (this.isDelim(QUESTIONMARK)) {
          eatQuestionMarkSequence.call(this, 6 - hexLength);
          break;
        }
        if (this.tokenType === types2.Dimension || this.tokenType === types2.Number) {
          startsWith.call(this, HYPHENMINUS);
          eatHexSequence.call(this, 1, false);
          break;
        }
        break;
      case types2.Dimension:
        hexLength = eatHexSequence.call(this, 1, true);
        if (hexLength > 0) {
          eatQuestionMarkSequence.call(this, 6 - hexLength);
        }
        break;
      default:
        this.eatDelim(PLUSSIGN);
        if (this.tokenType === types2.Ident) {
          hexLength = eatHexSequence.call(this, 0, true);
          if (hexLength > 0) {
            eatQuestionMarkSequence.call(this, 6 - hexLength);
          }
          break;
        }
        if (this.isDelim(QUESTIONMARK)) {
          this.next();
          eatQuestionMarkSequence.call(this, 5);
          break;
        }
        this.error("Hex digit or question mark is expected");
    }
  }
  var name = "UnicodeRange";
  var structure = {
    value: String
  };
  function parse3() {
    const start = this.tokenStart;
    this.eatIdent("u");
    scanUnicodeRange.call(this);
    return {
      type: "UnicodeRange",
      loc: this.getLocation(start, this.tokenStart),
      value: this.substrToCursor(start)
    };
  }
  function generate2(node2) {
    this.tokenize(node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/url.cjs
var require_url = __commonJS((exports) => {
  var charCodeDefinitions = require_char_code_definitions();
  var utils = require_utils();
  var SPACE = 32;
  var REVERSE_SOLIDUS = 92;
  var QUOTATION_MARK = 34;
  var APOSTROPHE = 39;
  var LEFTPARENTHESIS = 40;
  var RIGHTPARENTHESIS = 41;
  function decode(str) {
    const len = str.length;
    let start = 4;
    let end = str.charCodeAt(len - 1) === RIGHTPARENTHESIS ? len - 2 : len - 1;
    let decoded = "";
    while (start < end && charCodeDefinitions.isWhiteSpace(str.charCodeAt(start))) {
      start++;
    }
    while (start < end && charCodeDefinitions.isWhiteSpace(str.charCodeAt(end))) {
      end--;
    }
    for (let i = start;i <= end; i++) {
      let code = str.charCodeAt(i);
      if (code === REVERSE_SOLIDUS) {
        if (i === end) {
          if (i !== len - 1) {
            decoded = str.substr(i + 1);
          }
          break;
        }
        code = str.charCodeAt(++i);
        if (charCodeDefinitions.isValidEscape(REVERSE_SOLIDUS, code)) {
          const escapeStart = i - 1;
          const escapeEnd = utils.consumeEscaped(str, escapeStart);
          i = escapeEnd - 1;
          decoded += utils.decodeEscaped(str.substring(escapeStart + 1, escapeEnd));
        } else {
          if (code === 13 && str.charCodeAt(i + 1) === 10) {
            i++;
          }
        }
      } else {
        decoded += str[i];
      }
    }
    return decoded;
  }
  function encode(str) {
    let encoded = "";
    let wsBeforeHexIsNeeded = false;
    for (let i = 0;i < str.length; i++) {
      const code = str.charCodeAt(i);
      if (code === 0) {
        encoded += "�";
        continue;
      }
      if (code <= 31 || code === 127) {
        encoded += "\\" + code.toString(16);
        wsBeforeHexIsNeeded = true;
        continue;
      }
      if (code === SPACE || code === REVERSE_SOLIDUS || code === QUOTATION_MARK || code === APOSTROPHE || code === LEFTPARENTHESIS || code === RIGHTPARENTHESIS) {
        encoded += "\\" + str.charAt(i);
        wsBeforeHexIsNeeded = false;
      } else {
        if (wsBeforeHexIsNeeded && charCodeDefinitions.isHexDigit(code)) {
          encoded += " ";
        }
        encoded += str.charAt(i);
        wsBeforeHexIsNeeded = false;
      }
    }
    return "url(" + encoded + ")";
  }
  exports.decode = decode;
  exports.encode = encode;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Url.cjs
var require_Url = __commonJS((exports) => {
  var url = require_url();
  var string = require_string();
  var types2 = require_types();
  var name = "Url";
  var structure = {
    value: String
  };
  function parse3() {
    const start = this.tokenStart;
    let value;
    switch (this.tokenType) {
      case types2.Url:
        value = url.decode(this.consume(types2.Url));
        break;
      case types2.Function:
        if (!this.cmpStr(this.tokenStart, this.tokenEnd, "url(")) {
          this.error("Function name must be `url`");
        }
        this.eat(types2.Function);
        this.skipSC();
        value = string.decode(this.consume(types2.String));
        this.skipSC();
        if (!this.eof) {
          this.eat(types2.RightParenthesis);
        }
        break;
      default:
        this.error("Url or Function is expected");
    }
    return {
      type: "Url",
      loc: this.getLocation(start, this.tokenStart),
      value
    };
  }
  function generate2(node2) {
    this.token(types2.Url, url.encode(node2.value));
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/Value.cjs
var require_Value = __commonJS((exports) => {
  var name = "Value";
  var structure = {
    children: [[]]
  };
  function parse3() {
    const start = this.tokenStart;
    const children = this.readSequence(this.scope.Value);
    return {
      type: "Value",
      loc: this.getLocation(start, this.tokenStart),
      children
    };
  }
  function generate2(node2) {
    this.children(node2);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/WhiteSpace.cjs
var require_WhiteSpace = __commonJS((exports) => {
  var types2 = require_types();
  var SPACE = Object.freeze({
    type: "WhiteSpace",
    loc: null,
    value: " "
  });
  var name = "WhiteSpace";
  var structure = {
    value: String
  };
  function parse3() {
    this.eat(types2.WhiteSpace);
    return SPACE;
  }
  function generate2(node2) {
    this.token(types2.WhiteSpace, node2.value);
  }
  exports.generate = generate2;
  exports.name = name;
  exports.parse = parse3;
  exports.structure = structure;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/index.cjs
var require_node = __commonJS((exports) => {
  var AnPlusB = require_AnPlusB();
  var Atrule = require_Atrule();
  var AtrulePrelude = require_AtrulePrelude();
  var AttributeSelector = require_AttributeSelector();
  var Block = require_Block();
  var Brackets = require_Brackets();
  var CDC = require_CDC();
  var CDO = require_CDO();
  var ClassSelector = require_ClassSelector();
  var Combinator = require_Combinator();
  var Comment3 = require_Comment();
  var Condition = require_Condition();
  var Declaration = require_Declaration();
  var DeclarationList = require_DeclarationList();
  var Dimension = require_Dimension();
  var Feature = require_Feature();
  var FeatureFunction = require_FeatureFunction();
  var FeatureRange = require_FeatureRange();
  var Function = require_Function();
  var GeneralEnclosed = require_GeneralEnclosed();
  var Hash = require_Hash();
  var Identifier = require_Identifier();
  var IdSelector = require_IdSelector();
  var Layer = require_Layer();
  var LayerList = require_LayerList();
  var MediaQuery = require_MediaQuery();
  var MediaQueryList = require_MediaQueryList();
  var NestingSelector = require_NestingSelector();
  var Nth = require_Nth();
  var Number$1 = require_Number();
  var Operator = require_Operator();
  var Parentheses = require_Parentheses();
  var Percentage = require_Percentage();
  var PseudoClassSelector = require_PseudoClassSelector();
  var PseudoElementSelector = require_PseudoElementSelector();
  var Ratio = require_Ratio();
  var Raw = require_Raw();
  var Rule = require_Rule();
  var Scope = require_Scope();
  var Selector = require_Selector();
  var SelectorList = require_SelectorList();
  var String$1 = require_String();
  var StyleSheet = require_StyleSheet();
  var SupportsDeclaration = require_SupportsDeclaration();
  var TypeSelector = require_TypeSelector();
  var UnicodeRange = require_UnicodeRange();
  var Url = require_Url();
  var Value = require_Value();
  var WhiteSpace = require_WhiteSpace();
  exports.AnPlusB = AnPlusB;
  exports.Atrule = Atrule;
  exports.AtrulePrelude = AtrulePrelude;
  exports.AttributeSelector = AttributeSelector;
  exports.Block = Block;
  exports.Brackets = Brackets;
  exports.CDC = CDC;
  exports.CDO = CDO;
  exports.ClassSelector = ClassSelector;
  exports.Combinator = Combinator;
  exports.Comment = Comment3;
  exports.Condition = Condition;
  exports.Declaration = Declaration;
  exports.DeclarationList = DeclarationList;
  exports.Dimension = Dimension;
  exports.Feature = Feature;
  exports.FeatureFunction = FeatureFunction;
  exports.FeatureRange = FeatureRange;
  exports.Function = Function;
  exports.GeneralEnclosed = GeneralEnclosed;
  exports.Hash = Hash;
  exports.Identifier = Identifier;
  exports.IdSelector = IdSelector;
  exports.Layer = Layer;
  exports.LayerList = LayerList;
  exports.MediaQuery = MediaQuery;
  exports.MediaQueryList = MediaQueryList;
  exports.NestingSelector = NestingSelector;
  exports.Nth = Nth;
  exports.Number = Number$1;
  exports.Operator = Operator;
  exports.Parentheses = Parentheses;
  exports.Percentage = Percentage;
  exports.PseudoClassSelector = PseudoClassSelector;
  exports.PseudoElementSelector = PseudoElementSelector;
  exports.Ratio = Ratio;
  exports.Raw = Raw;
  exports.Rule = Rule;
  exports.Scope = Scope;
  exports.Selector = Selector;
  exports.SelectorList = SelectorList;
  exports.String = String$1;
  exports.StyleSheet = StyleSheet;
  exports.SupportsDeclaration = SupportsDeclaration;
  exports.TypeSelector = TypeSelector;
  exports.UnicodeRange = UnicodeRange;
  exports.Url = Url;
  exports.Value = Value;
  exports.WhiteSpace = WhiteSpace;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/config/lexer.cjs
var require_lexer = __commonJS((exports, module) => {
  var genericConst = require_generic_const();
  var data = require_data();
  var index = require_node();
  var lexerConfig = {
    generic: true,
    cssWideKeywords: genericConst.cssWideKeywords,
    ...data,
    node: index
  };
  module.exports = lexerConfig;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/scope/default.cjs
var require_default = __commonJS((exports, module) => {
  var types2 = require_types();
  var NUMBERSIGN = 35;
  var ASTERISK = 42;
  var PLUSSIGN = 43;
  var HYPHENMINUS = 45;
  var SOLIDUS = 47;
  var U = 117;
  function defaultRecognizer(context) {
    switch (this.tokenType) {
      case types2.Hash:
        return this.Hash();
      case types2.Comma:
        return this.Operator();
      case types2.LeftParenthesis:
        return this.Parentheses(this.readSequence, context.recognizer);
      case types2.LeftSquareBracket:
        return this.Brackets(this.readSequence, context.recognizer);
      case types2.String:
        return this.String();
      case types2.Dimension:
        return this.Dimension();
      case types2.Percentage:
        return this.Percentage();
      case types2.Number:
        return this.Number();
      case types2.Function:
        return this.cmpStr(this.tokenStart, this.tokenEnd, "url(") ? this.Url() : this.Function(this.readSequence, context.recognizer);
      case types2.Url:
        return this.Url();
      case types2.Ident:
        if (this.cmpChar(this.tokenStart, U) && this.cmpChar(this.tokenStart + 1, PLUSSIGN)) {
          return this.UnicodeRange();
        } else {
          return this.Identifier();
        }
      case types2.Delim: {
        const code = this.charCodeAt(this.tokenStart);
        if (code === SOLIDUS || code === ASTERISK || code === PLUSSIGN || code === HYPHENMINUS) {
          return this.Operator();
        }
        if (code === NUMBERSIGN) {
          this.error("Hex or identifier is expected", this.tokenStart + 1);
        }
        break;
      }
    }
  }
  module.exports = defaultRecognizer;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/scope/atrulePrelude.cjs
var require_atrulePrelude = __commonJS((exports, module) => {
  var _default = require_default();
  var atrulePrelude = {
    getNode: _default
  };
  module.exports = atrulePrelude;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/scope/selector.cjs
var require_selector = __commonJS((exports, module) => {
  var types2 = require_types();
  var NUMBERSIGN = 35;
  var AMPERSAND = 38;
  var ASTERISK = 42;
  var PLUSSIGN = 43;
  var SOLIDUS = 47;
  var FULLSTOP = 46;
  var GREATERTHANSIGN = 62;
  var VERTICALLINE = 124;
  var TILDE = 126;
  function onWhiteSpace(next, children) {
    if (children.last !== null && children.last.type !== "Combinator" && next !== null && next.type !== "Combinator") {
      children.push({
        type: "Combinator",
        loc: null,
        name: " "
      });
    }
  }
  function getNode() {
    switch (this.tokenType) {
      case types2.LeftSquareBracket:
        return this.AttributeSelector();
      case types2.Hash:
        return this.IdSelector();
      case types2.Colon:
        if (this.lookupType(1) === types2.Colon) {
          return this.PseudoElementSelector();
        } else {
          return this.PseudoClassSelector();
        }
      case types2.Ident:
        return this.TypeSelector();
      case types2.Number:
      case types2.Percentage:
        return this.Percentage();
      case types2.Dimension:
        if (this.charCodeAt(this.tokenStart) === FULLSTOP) {
          this.error("Identifier is expected", this.tokenStart + 1);
        }
        break;
      case types2.Delim: {
        const code = this.charCodeAt(this.tokenStart);
        switch (code) {
          case PLUSSIGN:
          case GREATERTHANSIGN:
          case TILDE:
          case SOLIDUS:
            return this.Combinator();
          case FULLSTOP:
            return this.ClassSelector();
          case ASTERISK:
          case VERTICALLINE:
            return this.TypeSelector();
          case NUMBERSIGN:
            return this.IdSelector();
          case AMPERSAND:
            return this.NestingSelector();
        }
        break;
      }
    }
  }
  var Selector = {
    onWhiteSpace,
    getNode
  };
  module.exports = Selector;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/function/expression.cjs
var require_expression = __commonJS((exports, module) => {
  function expressionFn() {
    return this.createSingleNodeList(this.Raw(null, false));
  }
  module.exports = expressionFn;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/function/var.cjs
var require_var = __commonJS((exports, module) => {
  var types2 = require_types();
  function varFn() {
    const children = this.createList();
    this.skipSC();
    children.push(this.Identifier());
    this.skipSC();
    if (this.tokenType === types2.Comma) {
      children.push(this.Operator());
      const startIndex = this.tokenIndex;
      const value = this.parseCustomProperty ? this.Value(null) : this.Raw(this.consumeUntilExclamationMarkOrSemicolon, false);
      if (value.type === "Value" && value.children.isEmpty) {
        for (let offset = startIndex - this.tokenIndex;offset <= 0; offset++) {
          if (this.lookupType(offset) === types2.WhiteSpace) {
            value.children.appendData({
              type: "WhiteSpace",
              loc: null,
              value: " "
            });
            break;
          }
        }
      }
      children.push(value);
    }
    return children;
  }
  module.exports = varFn;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/scope/value.cjs
var require_value = __commonJS((exports, module) => {
  var _default = require_default();
  var expression = require_expression();
  var _var = require_var();
  function isPlusMinusOperator(node2) {
    return node2 !== null && node2.type === "Operator" && (node2.value[node2.value.length - 1] === "-" || node2.value[node2.value.length - 1] === "+");
  }
  var value = {
    getNode: _default,
    onWhiteSpace(next, children) {
      if (isPlusMinusOperator(next)) {
        next.value = " " + next.value;
      }
      if (isPlusMinusOperator(children.last)) {
        children.last.value += " ";
      }
    },
    expression,
    var: _var
  };
  module.exports = value;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/scope/index.cjs
var require_scope = __commonJS((exports) => {
  var atrulePrelude = require_atrulePrelude();
  var selector = require_selector();
  var value = require_value();
  exports.AtrulePrelude = atrulePrelude;
  exports.Selector = selector;
  exports.Value = value;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/container.cjs
var require_container = __commonJS((exports, module) => {
  var types2 = require_types();
  var nonContainerNameKeywords = new Set(["none", "and", "not", "or"]);
  var container = {
    parse: {
      prelude() {
        const children = this.createList();
        if (this.tokenType === types2.Ident) {
          const name = this.substring(this.tokenStart, this.tokenEnd);
          if (!nonContainerNameKeywords.has(name.toLowerCase())) {
            children.push(this.Identifier());
          }
        }
        children.push(this.Condition("container"));
        return children;
      },
      block(nested = false) {
        return this.Block(nested);
      }
    }
  };
  module.exports = container;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/font-face.cjs
var require_font_face = __commonJS((exports, module) => {
  var fontFace = {
    parse: {
      prelude: null,
      block() {
        return this.Block(true);
      }
    }
  };
  module.exports = fontFace;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/import.cjs
var require_import = __commonJS((exports, module) => {
  var types2 = require_types();
  function parseWithFallback(parse3, fallback) {
    return this.parseWithFallback(() => {
      try {
        return parse3.call(this);
      } finally {
        this.skipSC();
        if (this.lookupNonWSType(0) !== types2.RightParenthesis) {
          this.error();
        }
      }
    }, fallback || (() => this.Raw(null, true)));
  }
  var parseFunctions = {
    layer() {
      this.skipSC();
      const children = this.createList();
      const node2 = parseWithFallback.call(this, this.Layer);
      if (node2.type !== "Raw" || node2.value !== "") {
        children.push(node2);
      }
      return children;
    },
    supports() {
      this.skipSC();
      const children = this.createList();
      const node2 = parseWithFallback.call(this, this.Declaration, () => parseWithFallback.call(this, () => this.Condition("supports")));
      if (node2.type !== "Raw" || node2.value !== "") {
        children.push(node2);
      }
      return children;
    }
  };
  var importAtrule = {
    parse: {
      prelude() {
        const children = this.createList();
        switch (this.tokenType) {
          case types2.String:
            children.push(this.String());
            break;
          case types2.Url:
          case types2.Function:
            children.push(this.Url());
            break;
          default:
            this.error("String or url() is expected");
        }
        this.skipSC();
        if (this.tokenType === types2.Ident && this.cmpStr(this.tokenStart, this.tokenEnd, "layer")) {
          children.push(this.Identifier());
        } else if (this.tokenType === types2.Function && this.cmpStr(this.tokenStart, this.tokenEnd, "layer(")) {
          children.push(this.Function(null, parseFunctions));
        }
        this.skipSC();
        if (this.tokenType === types2.Function && this.cmpStr(this.tokenStart, this.tokenEnd, "supports(")) {
          children.push(this.Function(null, parseFunctions));
        }
        if (this.lookupNonWSType(0) === types2.Ident || this.lookupNonWSType(0) === types2.LeftParenthesis) {
          children.push(this.MediaQueryList());
        }
        return children;
      },
      block: null
    }
  };
  module.exports = importAtrule;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/layer.cjs
var require_layer = __commonJS((exports, module) => {
  var layer = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.LayerList());
      },
      block() {
        return this.Block(false);
      }
    }
  };
  module.exports = layer;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/media.cjs
var require_media = __commonJS((exports, module) => {
  var media = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.MediaQueryList());
      },
      block(nested = false) {
        return this.Block(nested);
      }
    }
  };
  module.exports = media;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/nest.cjs
var require_nest = __commonJS((exports, module) => {
  var nest = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.SelectorList());
      },
      block() {
        return this.Block(true);
      }
    }
  };
  module.exports = nest;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/page.cjs
var require_page = __commonJS((exports, module) => {
  var page = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.SelectorList());
      },
      block() {
        return this.Block(true);
      }
    }
  };
  module.exports = page;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/scope.cjs
var require_scope2 = __commonJS((exports, module) => {
  var scope = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.Scope());
      },
      block(nested = false) {
        return this.Block(nested);
      }
    }
  };
  module.exports = scope;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/starting-style.cjs
var require_starting_style = __commonJS((exports, module) => {
  var startingStyle = {
    parse: {
      prelude: null,
      block(nested = false) {
        return this.Block(nested);
      }
    }
  };
  module.exports = startingStyle;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/supports.cjs
var require_supports = __commonJS((exports, module) => {
  var supports = {
    parse: {
      prelude() {
        return this.createSingleNodeList(this.Condition("supports"));
      },
      block(nested = false) {
        return this.Block(nested);
      }
    }
  };
  module.exports = supports;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/atrule/index.cjs
var require_atrule = __commonJS((exports, module) => {
  var container = require_container();
  var fontFace = require_font_face();
  var _import = require_import();
  var layer = require_layer();
  var media = require_media();
  var nest = require_nest();
  var page = require_page();
  var scope = require_scope2();
  var startingStyle = require_starting_style();
  var supports = require_supports();
  var atrule = {
    container,
    "font-face": fontFace,
    import: _import,
    layer,
    media,
    nest,
    page,
    scope,
    "starting-style": startingStyle,
    supports
  };
  module.exports = atrule;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/pseudo/lang.cjs
var require_lang = __commonJS((exports) => {
  var types2 = require_types();
  function parseLanguageRangeList() {
    const children = this.createList();
    this.skipSC();
    loop:
      while (!this.eof) {
        switch (this.tokenType) {
          case types2.Ident:
            children.push(this.Identifier());
            break;
          case types2.String:
            children.push(this.String());
            break;
          case types2.Comma:
            children.push(this.Operator());
            break;
          case types2.RightParenthesis:
            break loop;
          default:
            this.error("Identifier, string or comma is expected");
        }
        this.skipSC();
      }
    return children;
  }
  exports.parseLanguageRangeList = parseLanguageRangeList;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/pseudo/index.cjs
var require_pseudo = __commonJS((exports, module) => {
  var lang = require_lang();
  var selectorList = {
    parse() {
      return this.createSingleNodeList(this.SelectorList());
    }
  };
  var selector = {
    parse() {
      return this.createSingleNodeList(this.Selector());
    }
  };
  var identList = {
    parse() {
      return this.createSingleNodeList(this.Identifier());
    }
  };
  var langList = {
    parse: lang.parseLanguageRangeList
  };
  var nth = {
    parse() {
      return this.createSingleNodeList(this.Nth());
    }
  };
  var pseudo = {
    dir: identList,
    has: selectorList,
    lang: langList,
    matches: selectorList,
    is: selectorList,
    "-moz-any": selectorList,
    "-webkit-any": selectorList,
    where: selectorList,
    not: selectorList,
    "nth-child": nth,
    "nth-last-child": nth,
    "nth-last-of-type": nth,
    "nth-of-type": nth,
    slotted: selector,
    host: selector,
    "host-context": selector
  };
  module.exports = pseudo;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/node/index-parse.cjs
var require_index_parse = __commonJS((exports) => {
  var AnPlusB = require_AnPlusB();
  var Atrule = require_Atrule();
  var AtrulePrelude = require_AtrulePrelude();
  var AttributeSelector = require_AttributeSelector();
  var Block = require_Block();
  var Brackets = require_Brackets();
  var CDC = require_CDC();
  var CDO = require_CDO();
  var ClassSelector = require_ClassSelector();
  var Combinator = require_Combinator();
  var Comment3 = require_Comment();
  var Condition = require_Condition();
  var Declaration = require_Declaration();
  var DeclarationList = require_DeclarationList();
  var Dimension = require_Dimension();
  var Feature = require_Feature();
  var FeatureFunction = require_FeatureFunction();
  var FeatureRange = require_FeatureRange();
  var Function = require_Function();
  var GeneralEnclosed = require_GeneralEnclosed();
  var Hash = require_Hash();
  var Identifier = require_Identifier();
  var IdSelector = require_IdSelector();
  var Layer = require_Layer();
  var LayerList = require_LayerList();
  var MediaQuery = require_MediaQuery();
  var MediaQueryList = require_MediaQueryList();
  var NestingSelector = require_NestingSelector();
  var Nth = require_Nth();
  var Number2 = require_Number();
  var Operator = require_Operator();
  var Parentheses = require_Parentheses();
  var Percentage = require_Percentage();
  var PseudoClassSelector = require_PseudoClassSelector();
  var PseudoElementSelector = require_PseudoElementSelector();
  var Ratio = require_Ratio();
  var Raw = require_Raw();
  var Rule = require_Rule();
  var Scope = require_Scope();
  var Selector = require_Selector();
  var SelectorList = require_SelectorList();
  var String2 = require_String();
  var StyleSheet = require_StyleSheet();
  var SupportsDeclaration = require_SupportsDeclaration();
  var TypeSelector = require_TypeSelector();
  var UnicodeRange = require_UnicodeRange();
  var Url = require_Url();
  var Value = require_Value();
  var WhiteSpace = require_WhiteSpace();
  exports.AnPlusB = AnPlusB.parse;
  exports.Atrule = Atrule.parse;
  exports.AtrulePrelude = AtrulePrelude.parse;
  exports.AttributeSelector = AttributeSelector.parse;
  exports.Block = Block.parse;
  exports.Brackets = Brackets.parse;
  exports.CDC = CDC.parse;
  exports.CDO = CDO.parse;
  exports.ClassSelector = ClassSelector.parse;
  exports.Combinator = Combinator.parse;
  exports.Comment = Comment3.parse;
  exports.Condition = Condition.parse;
  exports.Declaration = Declaration.parse;
  exports.DeclarationList = DeclarationList.parse;
  exports.Dimension = Dimension.parse;
  exports.Feature = Feature.parse;
  exports.FeatureFunction = FeatureFunction.parse;
  exports.FeatureRange = FeatureRange.parse;
  exports.Function = Function.parse;
  exports.GeneralEnclosed = GeneralEnclosed.parse;
  exports.Hash = Hash.parse;
  exports.Identifier = Identifier.parse;
  exports.IdSelector = IdSelector.parse;
  exports.Layer = Layer.parse;
  exports.LayerList = LayerList.parse;
  exports.MediaQuery = MediaQuery.parse;
  exports.MediaQueryList = MediaQueryList.parse;
  exports.NestingSelector = NestingSelector.parse;
  exports.Nth = Nth.parse;
  exports.Number = Number2.parse;
  exports.Operator = Operator.parse;
  exports.Parentheses = Parentheses.parse;
  exports.Percentage = Percentage.parse;
  exports.PseudoClassSelector = PseudoClassSelector.parse;
  exports.PseudoElementSelector = PseudoElementSelector.parse;
  exports.Ratio = Ratio.parse;
  exports.Raw = Raw.parse;
  exports.Rule = Rule.parse;
  exports.Scope = Scope.parse;
  exports.Selector = Selector.parse;
  exports.SelectorList = SelectorList.parse;
  exports.String = String2.parse;
  exports.StyleSheet = StyleSheet.parse;
  exports.SupportsDeclaration = SupportsDeclaration.parse;
  exports.TypeSelector = TypeSelector.parse;
  exports.UnicodeRange = UnicodeRange.parse;
  exports.Url = Url.parse;
  exports.Value = Value.parse;
  exports.WhiteSpace = WhiteSpace.parse;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/config/parser.cjs
var require_parser = __commonJS((exports, module) => {
  var index = require_scope();
  var index$1 = require_atrule();
  var index$2 = require_pseudo();
  var indexParse = require_index_parse();
  var config = {
    parseContext: {
      default: "StyleSheet",
      stylesheet: "StyleSheet",
      atrule: "Atrule",
      atrulePrelude(options) {
        return this.AtrulePrelude(options.atrule ? String(options.atrule) : null);
      },
      mediaQueryList: "MediaQueryList",
      mediaQuery: "MediaQuery",
      condition(options) {
        return this.Condition(options.kind);
      },
      rule: "Rule",
      selectorList: "SelectorList",
      selector: "Selector",
      block() {
        return this.Block(true);
      },
      declarationList: "DeclarationList",
      declaration: "Declaration",
      value: "Value"
    },
    features: {
      supports: {
        selector() {
          return this.Selector();
        }
      },
      container: {
        style() {
          return this.Declaration();
        }
      }
    },
    scope: index,
    atrule: index$1,
    pseudo: index$2,
    node: indexParse
  };
  module.exports = config;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/config/walker.cjs
var require_walker = __commonJS((exports, module) => {
  var index = require_node();
  var config = {
    node: index
  };
  module.exports = config;
});

// ../imp-pinned/node_modules/css-tree/cjs/syntax/index.cjs
var require_syntax = __commonJS((exports, module) => {
  var create = require_create5();
  var lexer = require_lexer();
  var parser = require_parser();
  var walker = require_walker();
  var syntax = create({
    ...lexer,
    ...parser,
    ...walker
  });
  module.exports = syntax;
});

// ../imp-pinned/node_modules/css-tree/package.json
var require_package = __commonJS((exports, module) => {
  module.exports = {
    name: "css-tree",
    version: "3.2.1",
    description: "A tool set for CSS: fast detailed parser (CSS → AST), walker (AST traversal), generator (AST → CSS) and lexer (validation and matching) based on specs and browser implementations",
    author: "Roman Dvornov <rdvornov@gmail.com> (https://github.com/lahmatiy)",
    license: "MIT",
    repository: "csstree/csstree",
    keywords: [
      "css",
      "ast",
      "tokenizer",
      "parser",
      "walker",
      "lexer",
      "generator",
      "utils",
      "syntax",
      "validation"
    ],
    type: "module",
    module: "./lib/index.js",
    sideEffects: false,
    main: "./cjs/index.cjs",
    exports: {
      ".": {
        import: "./lib/index.js",
        require: "./cjs/index.cjs"
      },
      "./dist/*": "./dist/*.js",
      "./package.json": "./package.json",
      "./tokenizer": {
        import: "./lib/tokenizer/index.js",
        require: "./cjs/tokenizer/index.cjs"
      },
      "./parser": {
        import: "./lib/parser/index.js",
        require: "./cjs/parser/index.cjs"
      },
      "./selector-parser": {
        import: "./lib/parser/parse-selector.js",
        require: "./cjs/parser/parse-selector.cjs"
      },
      "./generator": {
        import: "./lib/generator/index.js",
        require: "./cjs/generator/index.cjs"
      },
      "./walker": {
        import: "./lib/walker/index.js",
        require: "./cjs/walker/index.cjs"
      },
      "./convertor": {
        import: "./lib/convertor/index.js",
        require: "./cjs/convertor/index.cjs"
      },
      "./lexer": {
        import: "./lib/lexer/index.js",
        require: "./cjs/lexer/index.cjs"
      },
      "./definition-syntax": {
        import: "./lib/definition-syntax/index.js",
        require: "./cjs/definition-syntax/index.cjs"
      },
      "./definition-syntax-data": {
        import: "./lib/data.js",
        require: "./cjs/data.cjs"
      },
      "./definition-syntax-data-patch": {
        import: "./lib/data-patch.js",
        require: "./cjs/data-patch.cjs"
      },
      "./utils": {
        import: "./lib/utils/index.js",
        require: "./cjs/utils/index.cjs"
      }
    },
    browser: {
      "./cjs/data.cjs": "./dist/data.cjs",
      "./cjs/version.cjs": "./dist/version.cjs",
      "./lib/data.js": "./dist/data.js",
      "./lib/version.js": "./dist/version.js"
    },
    unpkg: "dist/csstree.esm.js",
    jsdelivr: "dist/csstree.esm.js",
    scripts: {
      watch: "npm run build -- --watch",
      build: "npm run bundle && npm run esm-to-cjs --",
      "build-and-test": "npm run build && npm run test:dist && npm run test:cjs",
      bundle: "node scripts/bundle",
      "bundle-and-test": "npm run bundle && npm run test:dist",
      "esm-to-cjs": "node scripts/esm-to-cjs.cjs",
      "esm-to-cjs-and-test": "npm run esm-to-cjs && npm run test:cjs",
      lint: "eslint lib scripts && node scripts/review-syntax-patch --lint && node scripts/update-docs --lint",
      "lint-and-test": "npm run lint && npm test",
      "update:docs": "node scripts/update-docs",
      "review:syntax-patch": "node scripts/review-syntax-patch",
      test: "mocha lib/__tests --require lib/__tests/helpers/setup.js --reporter progress",
      "test:cjs": "mocha cjs/__tests --require lib/__tests/helpers/setup.js --reporter progress",
      "test:dist": "mocha dist/__tests --reporter progress",
      coverage: "c8 --exclude lib/__tests --reporter=lcovonly npm test",
      prepublishOnly: "npm run lint-and-test && npm run build-and-test"
    },
    dependencies: {
      "mdn-data": "2.27.1",
      "source-map-js": "^1.2.1"
    },
    devDependencies: {
      c8: "^11.0.0",
      clap: "^2.0.1",
      esbuild: "^0.27.3",
      eslint: "^8.50.0",
      "json-to-ast": "^2.1.0",
      mocha: "^9.2.2",
      rollup: "^2.80.0"
    },
    engines: {
      node: "^10 || ^12.20.0 || ^14.13.0 || >=15.0.0"
    },
    files: [
      "data",
      "dist",
      "cjs",
      "!cjs/__tests",
      "lib",
      "!lib/__tests"
    ]
  };
});

// ../imp-pinned/node_modules/css-tree/cjs/version.cjs
var require_version = __commonJS((exports) => {
  var { version } = require_package();
  exports.version = version;
});

// ../imp-pinned/node_modules/css-tree/cjs/definition-syntax/index.cjs
var require_definition_syntax = __commonJS((exports) => {
  var SyntaxError2 = require_SyntaxError2();
  var generate2 = require_generate();
  var parse3 = require_parse();
  var walk = require_walk();
  exports.SyntaxError = SyntaxError2.SyntaxError;
  exports.generate = generate2.generate;
  exports.parse = parse3.parse;
  exports.walk = walk.walk;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/clone.cjs
var require_clone = __commonJS((exports) => {
  var List = require_List();
  function clone(node2) {
    const result = {};
    for (const key of Object.keys(node2)) {
      let value = node2[key];
      if (value) {
        if (Array.isArray(value) || value instanceof List.List) {
          value = value.map(clone);
        } else if (value.constructor === Object) {
          value = clone(value);
        }
      }
      result[key] = value;
    }
    return result;
  }
  exports.clone = clone;
});

// ../imp-pinned/node_modules/css-tree/cjs/utils/ident.cjs
var require_ident = __commonJS((exports) => {
  var charCodeDefinitions = require_char_code_definitions();
  var utils = require_utils();
  var REVERSE_SOLIDUS = 92;
  function decode(str) {
    const end = str.length - 1;
    let decoded = "";
    for (let i = 0;i < str.length; i++) {
      let code = str.charCodeAt(i);
      if (code === REVERSE_SOLIDUS) {
        if (i === end) {
          break;
        }
        code = str.charCodeAt(++i);
        if (charCodeDefinitions.isValidEscape(REVERSE_SOLIDUS, code)) {
          const escapeStart = i - 1;
          const escapeEnd = utils.consumeEscaped(str, escapeStart);
          i = escapeEnd - 1;
          decoded += utils.decodeEscaped(str.substring(escapeStart + 1, escapeEnd));
        } else {
          if (code === 13 && str.charCodeAt(i + 1) === 10) {
            i++;
          }
        }
      } else {
        decoded += str[i];
      }
    }
    return decoded;
  }
  function encode(str) {
    let encoded = "";
    if (str.length === 1 && str.charCodeAt(0) === 45) {
      return "\\-";
    }
    for (let i = 0;i < str.length; i++) {
      const code = str.charCodeAt(i);
      if (code === 0) {
        encoded += "�";
        continue;
      }
      if (code <= 31 || code === 127 || code >= 48 && code <= 57 && (i === 0 || i === 1 && str.charCodeAt(0) === 45)) {
        encoded += "\\" + code.toString(16) + " ";
        continue;
      }
      if (charCodeDefinitions.isName(code)) {
        encoded += str.charAt(i);
      } else {
        encoded += "\\" + str.charAt(i);
      }
    }
    return encoded;
  }
  exports.decode = decode;
  exports.encode = encode;
});

// ../imp-pinned/node_modules/css-tree/cjs/index.cjs
var require_cjs = __commonJS((exports) => {
  var index$1 = require_syntax();
  var version = require_version();
  var create = require_create5();
  var List = require_List();
  var Lexer = require_Lexer();
  var index = require_definition_syntax();
  var clone = require_clone();
  var names$1 = require_names2();
  var ident = require_ident();
  var string = require_string();
  var url = require_url();
  var types2 = require_types();
  var names = require_names();
  var TokenStream = require_TokenStream();
  var OffsetToLocation = require_OffsetToLocation();
  var {
    tokenize,
    parse: parse3,
    generate: generate2,
    lexer,
    createLexer,
    walk,
    find: find2,
    findLast,
    findAll: findAll3,
    toPlainObject,
    fromPlainObject,
    fork
  } = index$1;
  exports.version = version.version;
  exports.createSyntax = create;
  exports.List = List.List;
  exports.Lexer = Lexer.Lexer;
  exports.definitionSyntax = index;
  exports.clone = clone.clone;
  exports.isCustomProperty = names$1.isCustomProperty;
  exports.keyword = names$1.keyword;
  exports.property = names$1.property;
  exports.vendorPrefix = names$1.vendorPrefix;
  exports.ident = ident;
  exports.string = string;
  exports.url = url;
  exports.tokenTypes = types2;
  exports.tokenNames = names;
  exports.TokenStream = TokenStream.TokenStream;
  exports.OffsetToLocation = OffsetToLocation.OffsetToLocation;
  exports.createLexer = createLexer;
  exports.find = find2;
  exports.findAll = findAll3;
  exports.findLast = findLast;
  exports.fork = fork;
  exports.fromPlainObject = fromPlainObject;
  exports.generate = generate2;
  exports.lexer = lexer;
  exports.parse = parse3;
  exports.toPlainObject = toPlainObject;
  exports.tokenize = tokenize;
  exports.walk = walk;
});

// ../imp-pinned/node_modules/htmlparser2/dist/index.js
var exports_dist3 = {};
__export(exports_dist3, {
  parseFeed: () => parseFeed,
  parseDocument: () => parseDocument,
  getFeed: () => getFeed,
  createDocumentStream: () => createDocumentStream,
  Tokenizer: () => Tokenizer,
  QuoteType: () => QuoteType,
  Parser: () => Parser,
  ElementType: () => exports_dist,
  DomUtils: () => exports_dist2,
  DomHandler: () => DomHandler,
  DefaultHandler: () => DomHandler
});

// ../imp-pinned/node_modules/entities/dist/decode-codepoint.js
var decodeMap = new Map([
  [0, 65533],
  [128, 8364],
  [130, 8218],
  [131, 402],
  [132, 8222],
  [133, 8230],
  [134, 8224],
  [135, 8225],
  [136, 710],
  [137, 8240],
  [138, 352],
  [139, 8249],
  [140, 338],
  [142, 381],
  [145, 8216],
  [146, 8217],
  [147, 8220],
  [148, 8221],
  [149, 8226],
  [150, 8211],
  [151, 8212],
  [152, 732],
  [153, 8482],
  [154, 353],
  [155, 8250],
  [156, 339],
  [158, 382],
  [159, 376]
]);
function replaceCodePoint(codePoint) {
  if (codePoint >= 55296 && codePoint <= 57343 || codePoint > 1114111) {
    return 65533;
  }
  return decodeMap.get(codePoint) ?? codePoint;
}

// ../imp-pinned/node_modules/entities/dist/internal/decode-shared.js
function decodeBase64(input) {
  const binary = atob(input);
  const evenLength = binary.length & ~1;
  const out = new Uint16Array(evenLength / 2);
  for (let index = 0, outIndex = 0;index < evenLength; index += 2) {
    const lo = binary.charCodeAt(index);
    const hi = binary.charCodeAt(index + 1);
    out[outIndex++] = lo | hi << 8;
  }
  return out;
}

// ../imp-pinned/node_modules/entities/dist/generated/decode-data-html.js
var htmlDecodeTree = /* @__PURE__ */ decodeBase64("QR08ALkAAgH6AYsDNQR2BO0EPgXZBQEGLAbdBxMISQrvCmQLfQurDKQNLw4fD4YPpA+6D/IPAAAAAAAAAAAAAAAAKhBMEY8TmxUWF2EYLBkxGuAa3RsJHDscWR8YIC8jSCSIJcMl6ie3Ku8rEC0CLjoupS7kLgAIRU1hYmNmZ2xtbm9wcnN0dVQAWgBeAGUAaQBzAHcAfgCBAIQAhwCSAJoAoACsALMAbABpAGcAO4DGAMZAUAA7gCYAJkBjAHUAdABlADuAwQDBQHIiZXZlAAJhAAFpeW0AcgByAGMAO4DCAMJAEGRyAADgNdgE3XIAYQB2AGUAO4DAAMBA8CFoYZFj4SFjcgBhZAAAoFMqAAFncIsAjgBvAG4ABGFmAADgNdg43fAlbHlGdW5jdGlvbgCgYSBpAG4AZwA7gMUAxUAAAWNzpACoAHIAAOA12Jzc6SFnbgCgVCJpAGwAZABlADuAwwDDQG0AbAA7gMQAxEAABGFjZWZvcnN1xQDYANoA7QDxAPYA+QD8AAABY3LJAM8AayNzbGFzaAAAoBYidgHTANUAAKDnKmUAZAAAoAYjeQARZIABY3J0AOAA5QDrAGEidXNlAACgNSLuI291bGxpcwCgLCFhAJJjcgAA4DXYBd1wAGYAAOA12Dnd5SF2ZdhiYwDyAOoAbSJwZXEAAKBOIgAHSE9hY2RlZmhpbG9yc3UXARoBHwE6AVIBVQFiAWQBZgGCAakB6QHtAfIBYwB5ACdkUABZADuAqQCpQIABY3B5ACUBKAE1AfUhdGUGYWmg0iJ0KGFsRGlmZmVyZW50aWFsRAAAoEUhbCJleXMAAKAtIQACYWVpb0EBRAFKAU0B8iFvbgxhZABpAGwAO4DHAMdAcgBjAAhhbiJpbnQAAKAwIm8AdAAKYQABZG5ZAV0BaSJsbGEAuGB0I2VyRG90ALdg8gA5AWkAp2NyImNsZQAAAkRNUFRwAXQBeQF9AW8AdAAAoJkiaSJudXMAAKCWIuwhdXMAoJUiaSJtZXMAAKCXIm8AAAFjc4cBlAFrKndpc2VDb250b3VySW50ZWdyYWwAAKAyImUjQ3VybHkAAAFEUZwBpAFvJXVibGVRdW90ZQAAoB0gdSJvdGUAAKAZIAACbG5wdbABtgHNAdgBbwBuAGWgNyIAoHQqgAFnaXQAvAHBAcUB8iJ1ZW50AKBhIm4AdAAAoC8i7yV1ckludGVncmFsAKAuIgABZnLRAdMBAKACIe8iZHVjdACgECJuLnRlckNsb2Nrd2lzZUNvbnRvdXJJbnRlZ3JhbAAAoDMi7yFzcwCgLypjAHIAAOA12J7ccABDoNMiYQBwAACgTSKABURKU1phY2VmaW9zAAsCEgIVAhgCGwIsAjQCOQI9AnMCfwNvoEUh9CJyYWhkAKARKWMAeQACZGMAeQAFZGMAeQAPZIABZ3JzACECJQIoAuchZXIAoCEgcgAAoKEhaAB2AACg5CoAAWF5MAIzAvIhb24OYRRkbAB0oAciYQCUY3IAAOA12AfdAAFhZkECawIAAWNtRQJnAvIjaXRpY2FsAAJBREdUUAJUAl8CYwJjInV0ZQC0YG8AdAFZAloC2WJiJGxlQWN1dGUA3WJyImF2ZQBgYGkibGRlANxi7yFuZACgxCJmJWVyZW50aWFsRAAAoEYhcAR9AgAAAAAAAIECjgIAABoDZgAA4DXYO91EoagAhQKJAm8AdAAAoNwgcSJ1YWwAAKBQIuIhbGUAA0NETFJVVpkCqAK1Au8C/wIRA28AbgB0AG8AdQByAEkAbgB0AGUAZwByAGEA7ADEAW8AdAKvAgAAAACwAqhgbiNBcnJvdwAAoNMhAAFlb7kC0AJmAHQAgAFBUlQAwQLGAs0CciJyb3cAAKDQIekkZ2h0QXJyb3cAoNQhZQDlACsCbgBnAAABTFLWAugC5SFmdAABQVLcAuECciJyb3cAAKD4J+kkZ2h0QXJyb3cAoPon6SRnaHRBcnJvdwCg+SdpImdodAAAAUFU9gL7AnIicm93AACg0iFlAGUAAKCoInAAQQIGAwAAAAALA3Iicm93AACg0SFvJHduQXJyb3cAAKDVIWUlcnRpY2FsQmFyAACgJSJuAAADQUJMUlRhJAM2AzoDWgNxA3oDciJyb3cAAKGTIUJVLAMwA2EAcgAAoBMpcCNBcnJvdwAAoPUhciJldmUAEWPlIWZ00gJDAwAASwMAAFIDaSVnaHRWZWN0b3IAAKBQKWUkZVZlY3RvcgAAoF4p5SJjdG9yQqC9IWEAcgAAoFYpaSJnaHQA1AFiAwAAaQNlJGVWZWN0b3IAAKBfKeUiY3RvckKgwSFhAHIAAKBXKWUAZQBBoKQiciJyb3cAAKCnIXIAcgBvAPcAtAIAAWN0gwOHA3IAAOA12J/c8iFvaxBhAAhOVGFjZGZnbG1vcHFzdHV4owOlA6kDsAO/A8IDxgPNA9ID8gP9AwEEFAQeBCAEJQRHAEphSAA7gNAA0EBjAHUAdABlADuAyQDJQIABYWl5ALYDuQO+A/Ihb24aYXIAYwA7gMoAykAtZG8AdAAWYXIAAOA12AjdcgBhAHYAZQA7gMgAyEDlIm1lbnQAoAgiAAFhcNYD2QNjAHIAEmF0AHkAUwLhAwAAAADpA20lYWxsU3F1YXJlAACg+yVlJ3J5U21hbGxTcXVhcmUAAKCrJQABZ3D2A/kDbwBuABhhZgAA4DXYPN3zImlsb26VY3UAAAFhaQYEDgRsAFSgdSppImxkZQAAoEIi7CNpYnJpdW0AoMwhAAFjaRgEGwRyAACgMCFtAACgcyphAJdjbQBsADuAywDLQAABaXApBC0E8yF0cwCgAyLvJG5lbnRpYWxFAKBHIYACY2Zpb3MAPQQ/BEMEXQRyBHkAJGRyAADgNdgJ3WwibGVkAFMCTAQAAAAAVARtJWFsbFNxdWFyZQAAoPwlZSdyeVNtYWxsU3F1YXJlAACgqiVwA2UEAABpBAAAAABtBGYAAOA12D3dwSFsbACgACLyI2llcnRyZgCgMSFjAPIAcQQABkpUYWJjZGZnb3JzdIgEiwSOBJMElwSkBKcEqwStBLIE5QTqBGMAeQADZDuAPgA+QO0hbWFkoJMD3GNyImV2ZQAeYYABZWl5AJ0EoASjBOQhaWwiYXIAYwAcYRNkbwB0ACBhcgAA4DXYCt0AoNkicABmAADgNdg+3eUiYXRlcgADRUZHTFNUvwTIBM8E1QTZBOAEcSJ1YWwATKBlIuUhc3MAoNsidSRsbEVxdWFsAACgZyJyI2VhdGVyAACgoirlIXNzAKB3IuwkYW50RXF1YWwAoH4qaSJsZGUAAKBzImMAcgAA4DXYotwAoGsiAARBYWNmaW9zdfkE/QQFBQgFCwUTBSIFKwVSIkRjeQAqZAABY3QBBQQFZQBrAMdiXmDpIXJjJGFyAACgDCFsJWJlcnRTcGFjZQAAoAsh8AEYBQAAGwVmAACgDSHpJXpvbnRhbExpbmUAoAAlAAFjdCYFKAXyABIF8iFvayZhbQBwAEQBMQU5BW8AdwBuAEgAdQBtAPAAAAFxInVhbAAAoE8iAAdFSk9hY2RmZ21ub3N0dVMFVgVZBVwFYwVtBXAFcwV6BZAFtgXFBckFzQVjAHkAFWTsIWlnMmFjAHkAAWRjAHUAdABlADuAzQDNQAABaXlnBWwFcgBjADuAzgDOQBhkbwB0ADBhcgAAoBEhcgBhAHYAZQA7gMwAzEAAoREhYXB/BYsFAAFjZ4MFhQVyACphaSNuYXJ5SQAAoEghbABpAGUA8wD6AvQBlQUAAKUFZaAsIgABZ3KaBZ4F8iFhbACgKyLzI2VjdGlvbgCgwiJpI3NpYmxlAAABQ1SsBbEFbyJtbWEAAKBjIGkibWVzAACgYiCAAWdwdAC8Bb8FwwVvAG4ALmFmAADgNdhA3WEAmWNjAHIAAKAQIWkibGRlAChh6wHSBQAA1QVjAHkABmRsADuAzwDPQIACY2Zvc3UA4QXpBe0F8gX9BQABaXnlBegFcgBjADRhGWRyAADgNdgN3XAAZgAA4DXYQd3jAfcFAAD7BXIAAOA12KXc8iFjeQhk6yFjeQRkgANISmFjZm9zAAwGDwYSBhUGHQYhBiYGYwB5ACVkYwB5AAxk8CFwYZpjAAFleRkGHAbkIWlsNmEaZHIAAOA12A7dcABmAADgNdhC3WMAcgAA4DXYptyABUpUYWNlZmxtb3N0AD0GQAZDBl4GawZkB2gHcAd0B80H2gdjAHkACWQ7gDwAPECAAmNtbnByAEwGTwZSBlUGWwb1IXRlOWHiIWRhm2NnAACg6ifsI2FjZXRyZgCgEiFyAACgniGAAWFleQBkBmcGagbyIW9uPWHkIWlsO2EbZAABZnNvBjQHdAAABUFDREZSVFVWYXKABp4GpAbGBssG3AYDByEHwQIqBwABbnKEBowGZyVsZUJyYWNrZXQAAKDoJ/Ihb3cAoZAhQlKTBpcGYQByAACg5CHpJGdodEFycm93AKDGIWUjaWxpbmcAAKAII28A9QGqBgAAsgZiJWxlQnJhY2tldAAAoOYnbgDUAbcGAAC+BmUkZVZlY3RvcgAAoGEp5SJjdG9yQqDDIWEAcgAAoFkpbCJvb3IAAKAKI2kiZ2h0AAABQVbSBtcGciJyb3cAAKCUIeUiY3RvcgCgTikAAWVy4AbwBmUAAKGjIkFW5gbrBnIicm93AACgpCHlImN0b3IAoFopaSNhbmdsZQBCorIi+wYAAAAA/wZhAHIAAKDPKXEidWFsAACgtCJwAIABRFRWAAoHEQcYB+8kd25WZWN0b3IAoFEpZSRlVmVjdG9yAACgYCnlImN0b3JCoL8hYQByAACgWCnlImN0b3JCoLwhYQByAACgUilpAGcAaAB0AGEAcgByAG8A9wDMAnMAAANFRkdMU1Q/B0cHTgdUB1gHXwfxJXVhbEdyZWF0ZXIAoNoidSRsbEVxdWFsAACgZiJyI2VhdGVyAACgdiLlIXNzAKChKuwkYW50RXF1YWwAoH0qaSJsZGUAAKByInIAAOA12A/dZaDYIuYjdGFycm93AKDaIWkiZG90AD9hgAFucHcAege1B7kHZwAAAkxSbHKCB5QHmwerB+UhZnQAAUFSiAeNB3Iicm93AACg9SfpJGdodEFycm93AKD3J+kkZ2h0QXJyb3cAoPYn5SFmdAABYXLcAqEHaQBnAGgAdABhAHIAcgBvAPcA5wJpAGcAaAB0AGEAcgByAG8A9wDuAmYAAOA12EPdZQByAAABTFK/B8YHZSRmdEFycm93AACgmSHpJGdodEFycm93AKCYIYABY2h0ANMH1QfXB/IAWgYAoLAh8iFva0FhAKBqIgAEYWNlZmlvc3XpB+wH7gf/BwMICQgOCBEIcAAAoAUpeQAcZAABZGzyB/kHaSR1bVNwYWNlAACgXyBsI2ludHJmAACgMyFyAADgNdgQ3e4jdXNQbHVzAKATInAAZgAA4DXYRN1jAPIA/gecY4AESmFjZWZvc3R1ACEIJAgoCDUIgQiFCDsKQApHCmMAeQAKZGMidXRlAENhgAFhZXkALggxCDQI8iFvbkdh5CFpbEVhHWSAAWdzdwA7CGEIfQjhInRpdmWAAU1UVgBECEwIWQhlJWRpdW1TcGFjZQAAoAsgaABpAAABY25SCFMIawBTAHAAYQBjAOUASwhlAHIAeQBUAGgAaQDuAFQI9CFlZAABR0xnCHUIcgBlAGEAdABlAHIARwByAGUAYQB0AGUA8gDrBGUAcwBzAEwAZQBzAPMA2wdMImluZQAKYHIAAOA12BHdAAJCbnB0jAiRCJkInAhyImVhawAAoGAgwiZyZWFraW5nU3BhY2WgYGYAAKAVIUOq7CqzCMIIzQgAAOcIGwkAAAAAAAAtCQAAbwkAAIcJAACdCcAJGQoAADQKAAFvdbYIvAjuI2dydWVudACgYiJwIkNhcAAAoG0ibyh1YmxlVmVydGljYWxCYXIAAKAmIoABbHF4ANII1wjhCOUibWVudACgCSL1IWFsVKBgImkibGRlAADgQiI4A2kic3RzAACgBCJyI2VhdGVyAACjbyJFRkdMU1T1CPoIAgkJCQ0JFQlxInVhbAAAoHEidSRsbEVxdWFsAADgZyI4A3IjZWF0ZXIAAOBrIjgD5SFzcwCgeSLsJGFudEVxdWFsAOB+KjgDaSJsZGUAAKB1IvUhbXBEASAJJwnvI3duSHVtcADgTiI4A3EidWFsAADgTyI4A2UAAAFmczEJRgn0JFRyaWFuZ2xlQqLqIj0JAAAAAEIJYQByAADgzyk4A3EidWFsAACg7CJzAICibiJFR0xTVABRCVYJXAlhCWkJcSJ1YWwAAKBwInIjZWF0ZXIAAKB4IuUhc3MA4GoiOAPsJGFudEVxdWFsAOB9KjgDaSJsZGUAAKB0IuUic3RlZAABR0x1CX8J8iZlYXRlckdyZWF0ZXIA4KIqOAPlI3NzTGVzcwDgoSo4A/IjZWNlZGVzAKGAIkVTjwmVCXEidWFsAADgryo4A+wkYW50RXF1YWwAoOAiAAFlaaAJqQl2JmVyc2VFbGVtZW50AACgDCLnJWh0VHJpYW5nbGVCousitgkAAAAAuwlhAHIAAODQKTgDcSJ1YWwAAKDtIgABcXXDCeAJdSNhcmVTdQAAAWJwywnVCfMhZXRF4I8iOANxInVhbAAAoOIi5SJyc2V0ReCQIjgDcSJ1YWwAAKDjIoABYmNwAOYJ8AkNCvMhZXRF4IIi0iBxInVhbAAAoIgi4yJlZWRzgKGBIkVTVAD6CQAKBwpxInVhbAAA4LAqOAPsJGFudEVxdWFsAKDhImkibGRlAADgfyI4A+UicnNldEXggyLSIHEidWFsAACgiSJpImxkZQCAoUEiRUZUACIKJwouCnEidWFsAACgRCJ1JGxsRXF1YWwAAKBHImkibGRlAACgSSJlJXJ0aWNhbEJhcgAAoCQiYwByAADgNdip3GkAbABkAGUAO4DRANFAnWMAB0VhY2RmZ21vcHJzdHV2XgphCmgKcgp2CnoKgQqRCpYKqwqtCrsKyArNCuwhaWdSYWMAdQB0AGUAO4DTANNAAAFpeWwKcQpyAGMAO4DUANRAHmRiImxhYwBQYXIAAOA12BLdcgBhAHYAZQA7gNIA0kCAAWFlaQCHCooKjQpjAHIATGFnAGEAqWNjInJvbgCfY3AAZgAA4DXYRt3lI25DdXJseQABRFGeCqYKbyV1YmxlUXVvdGUAAKAcIHUib3RlAACgGCAAoFQqAAFjbLEKtQpyAADgNdiq3GEAcwBoADuA2ADYQGkAbAHACsUKZABlADuA1QDVQGUAcwAAoDcqbQBsADuA1gDWQGUAcgAAAUJQ0wrmCgABYXLXCtoKcgAAoD4gYQBjAAABZWvgCuIKAKDeI2UAdAAAoLQjYSVyZW50aGVzaXMAAKDcI4AEYWNmaGlsb3JzAP0KAwsFCwkLCwsMCxELIwtaC3IjdGlhbEQAAKACInkAH2RyAADgNdgT3WkApmOgY/Ujc01pbnVzsWAAAWlwFQsgC24AYwBhAHIAZQBwAGwAYQBuAOUACgVmAACgGSGAobsqZWlvACoLRQtJC+MiZWRlc4CheiJFU1QANAs5C0ALcSJ1YWwAAKCvKuwkYW50RXF1YWwAoHwiaSJsZGUAAKB+Im0AZQAAoDMgAAFkcE0LUQv1IWN0AKAPIm8jcnRpb24AYaA3ImwAAKAdIgABY2leC2ILcgAA4DXYq9yoYwACVWZvc2oLbwtzC3cLTwBUADuAIgAiQHIAAOA12BTdcABmAACgGiFjAHIAAOA12KzcAAZCRWFjZWZoaW9yc3WPC5MLlwupC7YL2AvbC90LhQyTDJoMowzhIXJyAKAQKUcAO4CuAK5AgAFjbnIAnQugC6ML9SF0ZVRhZwAAoOsncgB0oKAhbAAAoBYpgAFhZXkArwuyC7UL8iFvblhh5CFpbFZhIGR2oBwhZSJyc2UAAAFFVb8LzwsAAWxxwwvIC+UibWVudACgCyL1JGlsaWJyaXVtAKDLIXAmRXF1aWxpYnJpdW0AAKBvKXIAAKAcIW8AoWPnIWh0AARBQ0RGVFVWYewLCgwQDDIMNwxeDHwM9gIAAW5y8Av4C2clbGVCcmFja2V0AACg6SfyIW93AKGSIUJM/wsDDGEAcgAAoOUhZSRmdEFycm93AACgxCFlI2lsaW5nAACgCSNvAPUBFgwAAB4MYiVsZUJyYWNrZXQAAKDnJ24A1AEjDAAAKgxlJGVWZWN0b3IAAKBdKeUiY3RvckKgwiFhAHIAAKBVKWwib29yAACgCyMAAWVyOwxLDGUAAKGiIkFWQQxGDHIicm93AACgpiHlImN0b3IAoFspaSNhbmdsZQBCorMiVgwAAAAAWgxhAHIAAKDQKXEidWFsAACgtSJwAIABRFRWAGUMbAxzDO8kd25WZWN0b3IAoE8pZSRlVmVjdG9yAACgXCnlImN0b3JCoL4hYQByAACgVCnlImN0b3JCoMAhYQByAACgUykAAXB1iQyMDGYAAKAdIe4kZEltcGxpZXMAoHAp6SRnaHRhcnJvdwCg2yEAAWNongyhDHIAAKAbIQCgsSHsJGVEZWxheWVkAKD0KYAGSE9hY2ZoaW1vcXN0dQC/DMgMzAzQDOIM5gwKDQ0NFA0ZDU8NVA1YDQABQ2PDDMYMyCFjeSlkeQAoZEYiVGN5ACxkYyJ1dGUAWmEAorwqYWVpedgM2wzeDOEM8iFvbmBh5CFpbF5hcgBjAFxhIWRyAADgNdgW3e8hcnQAAkRMUlXvDPYM/QwEDW8kd25BcnJvdwAAoJMhZSRmdEFycm93AACgkCHpJGdodEFycm93AKCSIXAjQXJyb3cAAKCRIechbWGjY+EkbGxDaXJjbGUAoBgicABmAADgNdhK3XICHw0AAAAAIg10AACgGiLhIXJlgKGhJUlTVQAqDTINSg3uJXRlcnNlY3Rpb24AoJMidQAAAWJwNw1ADfMhZXRFoI8icSJ1YWwAAKCRIuUicnNldEWgkCJxInVhbAAAoJIibiJpb24AAKCUImMAcgAA4DXYrtxhAHIAAKDGIgACYmNtcF8Nag2ODZANc6DQImUAdABFoNAicSJ1YWwAAKCGIgABY2huDYkNZSJlZHMAgKF7IkVTVAB4DX0NhA1xInVhbAAAoLAq7CRhbnRFcXVhbACgfSJpImxkZQAAoH8iVABoAGEA9ADHCwCgESIAodEiZXOVDZ8NciJzZXQARaCDInEidWFsAACghyJlAHQAAKDRIoAFSFJTYWNmaGlvcnMAtQ27Db8NyA3ODdsN3w3+DRgOHQ4jDk8AUgBOADuA3gDeQMEhREUAoCIhAAFIY8MNxg1jAHkAC2R5ACZkAAFidcwNzQ0JYKRjgAFhZXkA1A3XDdoN8iFvbmRh5CFpbGJhImRyAADgNdgX3QABZWnjDe4N8gHoDQAA7Q3lImZvcmUAoDQiYQCYYwABY27yDfkNayNTcGFjZQAA4F8gCiDTInBhY2UAoAkg7CFkZYChPCJFRlQABw4MDhMOcSJ1YWwAAKBDInUkbGxFcXVhbAAAoEUiaSJsZGUAAKBIInAAZgAA4DXYS93pI3BsZURvdACg2yAAAWN0Jw4rDnIAAOA12K/c8iFva2Zh4QpFDlYOYA5qDgAAbg5yDgAAAAAAAAAAAAB5DnwOqA6zDgAADg8RDxYPGg8AAWNySA5ODnUAdABlADuA2gDaQHIAb6CfIeMhaXIAoEkpcgDjAVsOAABdDnkADmR2AGUAbGEAAWl5Yw5oDnIAYwA7gNsA20AjZGIibGFjAHBhcgAA4DXYGN1yAGEAdgBlADuA2QDZQOEhY3JqYQABZGl/Dp8OZQByAAABQlCFDpcOAAFhcokOiw5yAF9gYQBjAAABZWuRDpMOAKDfI2UAdAAAoLUjYSVyZW50aGVzaXMAAKDdI28AbgBQoMMi7CF1cwCgjiIAAWdwqw6uDm8AbgByYWYAAOA12EzdAARBREVUYWRwc78O0g7ZDuEOBQPqDvMOBw9yInJvdwDCoZEhyA4AAMwOYQByAACgEilvJHduQXJyb3cAAKDFIW8kd25BcnJvdwAAoJUhcSV1aWxpYnJpdW0AAKBuKWUAZQBBoKUiciJyb3cAAKClIW8AdwBuAGEAcgByAG8A9wAQA2UAcgAAAUxS+Q4AD2UkZnRBcnJvdwAAoJYh6SRnaHRBcnJvdwCglyFpAGyg0gNvAG4ApWPpIW5nbmFjAHIAAOA12LDcaSJsZGUAaGFtAGwAO4DcANxAgAREYmNkZWZvc3YALQ8xDzUPNw89D3IPdg97D4AP4SFzaACgqyJhAHIAAKDrKnkAEmThIXNobKCpIgCg5ioAAWVyQQ9DDwCgwSKAAWJ0eQBJD00Paw9hAHIAAKAWIGmgFiDjIWFsAAJCTFNUWA9cD18PZg9hAHIAAKAjIukhbmV8YGUkcGFyYXRvcgAAoFgnaSJsZGUAAKBAItQkaGluU3BhY2UAoAogcgAA4DXYGd1wAGYAAOA12E3dYwByAADgNdix3GQiYXNoAACgqiKAAmNlZm9zAI4PkQ+VD5kPng/pIXJjdGHkIWdlAKDAInIAAOA12BrdcABmAADgNdhO3WMAcgAA4DXYstwAAmZpb3OqD64Prw+0D3IAAOA12BvdnmNwAGYAAOA12E/dYwByAADgNdiz3IAEQUlVYWNmb3N1AMgPyw/OD9EP2A/gD+QP6Q/uD2MAeQAvZGMAeQAHZGMAeQAuZGMAdQB0AGUAO4DdAN1AAAFpedwP3w9yAGMAdmErZHIAAOA12BzdcABmAADgNdhQ3WMAcgAA4DXYtNxtAGwAeGEABEhhY2RlZm9z/g8BEAUQDRAQEB0QIBAkEGMAeQAWZGMidXRlAHlhAAFheQkQDBDyIW9ufWEXZG8AdAB7YfIBFRAAABwQbwBXAGkAZAB0AOgAVAhhAJZjcgAAoCghcABmAACgJCFjAHIAAOA12LXc4QtCEEkQTRAAAGcQbRByEAAAAAAAAAAAeRCKEJcQ8hD9EAAAGxEhETIROREAAD4RYwB1AHQAZQA7gOEA4UByImV2ZQADYYCiPiJFZGl1eQBWEFkQWxBgEGUQAOA+IjMDAKA/InIAYwA7gOIA4kB0AGUAO4C0ALRAMGRsAGkAZwA7gOYA5kByoGEgAOA12B7dcgBhAHYAZQA7gOAA4EAAAWVwfBCGEAABZnCAEIQQ8yF5bQCgNSHoAIMQaABhALFjAAFhcI0QWwAAAWNskRCTEHIAAWFnAACgPypkApwQAAAAALEQAKInImFkc3ajEKcQqRCuEG4AZAAAoFUqAKBcKmwib3BlAACgWCoAoFoqAKMgImVsbXJzersQvRDAEN0Q5RDtEACgpCllAACgICJzAGQAYaAhImEEzhDQENIQ1BDWENgQ2hDcEACgqCkAoKkpAKCqKQCgqykAoKwpAKCtKQCgrikAoK8pdAB2oB8iYgBkoL4iAKCdKQABcHTpEOwQaAAAoCIixWDhIXJyAKB8IwABZ3D1EPgQbwBuAAVhZgAA4DXYUt0Ao0giRWFlaW9wBxEJEQ0RDxESERQRAKBwKuMhaXIAoG8qAKBKImQAAKBLInMAJ2DyIW94ZaBIIvEADhFpAG4AZwA7gOUA5UCAAWN0eQAmESoRKxFyAADgNdi23CpgbQBwAGWgSCLxAPgBaQBsAGQAZQA7gOMA40BtAGwAO4DkAORAAAFjaUERRxFvAG4AaQBuAPQA6AFuAHQAAKARKgAITmFiY2RlZmlrbG5vcHJzdWQRaBGXEZ8RpxGrEdIR1hErEjASexKKEn0RThNbE3oTbwB0AACg7SoAAWNybBGJEWsAAAJjZXBzdBF4EX0RghHvIW5nAKBMInAjc2lsb24A9mNyImltZQAAoDUgaQBtAGWgPSJxAACgzSJ2AY0RkRFlAGUAAKC9ImUAZABnoAUjZQAAoAUjcgBrAHSgtSPiIXJrAKC2IwABb3mjEaYRbgDnAHcRMWTxIXVvAKAeIIACY21wcnQAtBG5Eb4RwRHFEeEhdXPloDUi5ABwInR5dgAAoLApcwDpAH0RbgBvAPUA6gCAAWFodwDLEcwRzhGyYwCgNiHlIWVuAKBsInIAAOA12B/dZwCAA2Nvc3R1dncA4xHyEQUSEhIhEiYSKRKAAWFpdQDpEesR7xHwAKMFcgBjAACg7yVwAACgwyKAAWRwdAD4EfwRABJvAHQAAKAAKuwhdXMAoAEqaSJtZXMAAKACKnECCxIAAAAADxLjIXVwAKAGKmEAcgAAoAUm8iNpYW5nbGUAAWR1GhIeEu8hd24AoL0lcAAAoLMlcCJsdXMAAKAEKmUA5QBCD+UAkg9hInJvdwAAoA0pgAFha28ANhJoEncSAAFjbjoSZRJrAIABbHN0AEESRxJNEm8jemVuZ2UAAKDrKXEAdQBhAHIA5QBcBPIjaWFuZ2xlgKG0JWRscgBYElwSYBLvIXduAKC+JeUhZnQAoMIlaSJnaHQAAKC4JWsAAKAjJLEBbRIAAHUSsgFxEgAAcxIAoJIlAKCRJTQAAKCTJWMAawAAoIglAAFlb38ShxJx4D0A5SD1IWl2AOBhIuUgdAAAoBAjAAJwdHd4kRKVEpsSnxJmAADgNdhT3XSgpSJvAG0AAKClIvQhaWUAoMgiAAZESFVWYmRobXB0dXayEsES0RLgEvcS+xIKExoTHxMjEygTNxMAAkxSbHK5ErsSvRK/EgCgVyUAoFQlAKBWJQCgUyUAolAlRFVkdckSyxLNEs8SAKBmJQCgaSUAoGQlAKBnJQACTFJsctgS2hLcEt4SAKBdJQCgWiUAoFwlAKBZJQCjUSVITFJobHLrEu0S7xLxEvMS9RIAoGwlAKBjJQCgYCUAoGslAKBiJQCgXyVvAHgAAKDJKQACTFJscgITBBMGEwgTAKBVJQCgUiUAoBAlAKAMJQCiACVEVWR1EhMUExYTGBMAoGUlAKBoJQCgLCUAoDQlaSJudXMAAKCfIuwhdXMAoJ4iaSJtZXMAAKCgIgACTFJsci8TMRMzEzUTAKBbJQCgWCUAoBglAKAUJQCjAiVITFJobHJCE0QTRhNIE0oTTBMAoGolAKBhJQCgXiUAoDwlAKAkJQCgHCUAAWV2UhNVE3YA5QD5AGIAYQByADuApgCmQAACY2Vpb2ITZhNqE24TcgAA4DXYt9xtAGkAAKBPIG0A5aA9IogRbAAAoVwAYmh0E3YTAKDFKfMhdWIAoMgnbAF+E4QTbABloCIgdAAAoCIgcAAAoU4iRWWJE4sTAKCuKvGgTyI8BeEMqRMAAN8TABQDFB8UAAAjFDQUAAAAAIUUAAAAAI0UAAAAANcU4xT3FPsUAACIFQAAlhWAAWNwcgCuE7ET1RP1IXRlB2GAoikiYWJjZHMAuxO/E8QTzhPSE24AZAAAoEQqciJjdXAAAKBJKgABYXXIE8sTcAAAoEsqcAAAoEcqbwB0AACgQCoA4CkiAP4AAWVv2RPcE3QAAKBBIO4ABAUAAmFlaXXlE+8T9RP4E/AB6hMAAO0TcwAAoE0qbwBuAA1hZABpAGwAO4DnAOdAcgBjAAlhcABzAHOgTCptAACgUCpvAHQAC2GAAWRtbgAIFA0UEhRpAGwAO4C4ALhAcCJ0eXYAAKCyKXQAAIGiADtlGBQZFKJAcgBkAG8A9ABiAXIAAOA12CDdgAFjZWkAKBQqFDIUeQBHZGMAawBtoBMn4SFyawCgEyfHY3IAAKPLJUVjZWZtcz8UQRRHFHcUfBSAFACgwykAocYCZWxGFEkUcQAAoFciZQBhAlAUAAAAAGAUciJyb3cAAAFsclYUWhTlIWZ0AKC6IWkiZ2h0AACguyGAAlJTYWNkAGgUaRRrFG8UcxSuYACgyCRzAHQAAKCbIukhcmMAoJoi4SFzaACgnSJuImludAAAoBAqaQBkAACg7yrjIWlyAKDCKfUhYnN1oGMmaQB0AACgYybsApMUmhS2FAAAwxRvAG4AZaA6APGgVCKrAG0CnxQAAAAAoxRhAHSgLABAYAChASJmbKcUqRTuABMNZQAAAW14rhSyFOUhbnQAoAEiZQDzANIB5wG6FAAAwBRkoEUibwB0AACgbSpuAPQAzAGAAWZyeQDIFMsUzhQA4DXYVN1vAOQA1wEAgakAO3MeAdMUcgAAoBchAAFhb9oU3hRyAHIAAKC1IXMAcwAAoBcnAAFjdeYU6hRyAADgNdi43AABYnDuFPIUZaDPKgCg0SploNAqAKDSKuQhb3QAoO8igANkZWxwcnZ3AAYVEBUbFSEVRBVlFYQV4SFycgABbHIMFQ4VAKA4KQCgNSlwAhYVAAAAABkVcgAAoN4iYwAAoN8i4SFycnCgtiEAoD0pgKIqImJjZG9zACsVMBU6FT4VQRVyImNhcAAAoEgqAAFhdTQVNxVwAACgRipwAACgSipvAHQAAKCNInIAAKBFKgDgKiIA/gACYWxydksVURVuFXMVcgByAG2gtyEAoDwpeQCAAWV2dwBYFWUVaRVxAHACXxUAAAAAYxVyAGUA4wAXFXUA4wAZFWUAZQAAoM4iZSJkZ2UAAKDPImUAbgA7gKQApEBlI2Fycm93AAABbHJ7FX8V5SFmdACgtiFpImdodAAAoLchZQDkAG0VAAFjaYsVkRVvAG4AaQBuAPQAkwFuAHQAAKAxImwiY3R5AACgLSOACUFIYWJjZGVmaGlqbG9yc3R1d3oAuBW7Fb8V1RXgFegV+RUKFhUWHxZUFlcWZRbFFtsW7xb7FgUXChdyAPIAtAJhAHIAAKBlKQACZ2xyc8YVyhXOFdAV5yFlcgCgICDlIXRoAKA4IfIA9QxoAHagECAAoKMiawHZFd4VYSJyb3cAAKAPKWEA4wBfAgABYXnkFecV8iFvbg9hNGQAoUYhYW/tFfQVAAFnciEC8RVyAACgyiF0InNlcQAAoHcqgAFnbG0A/xUCFgUWO4CwALBAdABhALRjcCJ0eXYAAKCxKQABaXIOFhIW8yFodACgfykA4DXYId1hAHIAAAFschsWHRYAoMMhAKDCIYACYWVnc3YAKBauAjYWOhY+Fm0AAKHEIm9zLhY0Fm4AZABzoMQi9SFpdACgZiZhIm1tYQDdY2kAbgAAoPIiAKH3AGlvQxZRFmQAZQAAgfcAO29KFksW90BuI3RpbWVzAACgxyJuAPgAUBZjAHkAUmRjAG8CXhYAAAAAYhZyAG4AAKAeI28AcAAAoA0jgAJscHR1dwBuFnEWdRaSFp4W7CFhciRgZgAA4DXYVd0AotkCZW1wc30WhBaJFo0WcQBkoFAibwB0AACgUSJpIm51cwAAoDgi7CF1cwCgFCLxInVhcmUAoKEiYgBsAGUAYgBhAHIAdwBlAGQAZwDlANcAbgCAAWFkaAClFqoWtBZyAHIAbwD3APUMbwB3AG4AYQByAHIAbwB3APMA8xVhI3Jwb29uAAABbHK8FsAWZQBmAPQAHBZpAGcAaAD0AB4WYgHJFs8WawBhAHIAbwD3AJILbwLUFgAAAADYFnIAbgAAoB8jbwBwAACgDCOAAWNvdADhFukW7BYAAXJ55RboFgDgNdi53FVkbAAAoPYp8iFvaxFhAAFkcvMW9xZvAHQAAKDxImkA5qC/JVsSAAFhaP8WAhdyAPIANQNhAPIA1wvhIm5nbGUAoKYpAAFjaQ4XEBd5AF9k5yJyYXJyAKD/JwAJRGFjZGVmZ2xtbm9wcXJzdHV4MRc4F0YXWxcyBF4XaRd5F40XrBe0F78X2RcVGCEYLRg1GEAYAAFEbzUXgRZvAPQA+BUAAWNzPBdCF3UAdABlADuA6QDpQPQhZXIAoG4qAAJhaW95TRdQF1YXWhfyIW9uG2FyAGOgViI7gOoA6kDsIW9uAKBVIk1kbwB0ABdhAAFEcmIXZhdvAHQAAKBSIgDgNdgi3XKhmipuF3QXYQB2AGUAO4DoAOhAZKCWKm8AdAAAoJgqgKGZKmlscwCAF4UXhxfuInRlcnMAoOcjAKATIWSglSpvAHQAAKCXKoABYXBzAJMXlheiF2MAcgATYXQAeQBzogUinxcAAAAAoRdlAHQAAKAFInAAMaADIDMBqRerFwCgBCAAoAUgAAFnc7AXsRdLYXAAAKACIAABZ3C4F7sXbwBuABlhZgAA4DXYVt2AAWFscwDFF8sXzxdyAHOg1SJsAACg4yl1AHMAAKBxKmkAAKG1A2x21RfYF28AbgC1Y/VjAAJjc3V24BfoF/0XEBgAAWlv5BdWF3IAYwAAoFYiaQLuFwAAAADwF+0ADQThIW50AAFnbPUX+Rd0AHIAAKCWKuUhc3MAoJUqgAFhZWkAAxgGGAoYbABzAD1gcwB0AACgXyJ2AESgYSJEAACgeCrwImFyc2wAoOUpAAFEYRkYHRhvAHQAAKBTInIAcgAAoHEpgAFjZGkAJxgqGO0XcgAAoC8hbwD0AIwCAAFhaDEYMhi3YzuA8ADwQAABbXI5GD0YbAA7gOsA60BvAACgrCCAAWNpcABGGEgYSxhsACFgcwD0ACwEAAFlb08YVxhjAHQAYQB0AGkAbwDuABoEbgBlAG4AdABpAGEAbADlADME4Ql1GAAAgRgAAIMYiBgAAAAAoRilGAAAqhgAALsYvhjRGAAA1xgnGWwAbABpAG4AZwBkAG8AdABzAGUA8QBlF3kARGRtImFsZQAAoEAmgAFpbHIAjRiRGJ0Y7CFpZwCgA/tpApcYAAAAAJoYZwAAoAD7aQBnAACgBPsA4DXYI93sIWlnAKAB++whaWcA4GYAagCAAWFsdACvGLIYthh0AACgbSZpAGcAAKAC+24AcwAAoLElbwBmAJJh8AHCGAAAxhhmAADgNdhX3QABYWvJGMwYbADsAGsEdqDUIgCg2SphI3J0aW50AACgDSoAAWFv2hgiGQABY3PeGB8ZsQPnGP0YBRkSGRUZAAAdGbID7xjyGPQY9xj5GAAA+xg7gL0AvUAAoFMhO4C8ALxAAKBVIQCgWSEAoFshswEBGQAAAxkAoFQhAKBWIbQCCxkOGQAAAAAQGTuAvgC+QACgVyEAoFwhNQAAoFghtgEZGQAAGxkAoFohAKBdITgAAKBeIWwAAKBEIHcAbgAAoCIjYwByAADgNdi73IAIRWFiY2RlZmdpamxub3JzdHYARhlKGVoZXhlmGWkZkhmWGZkZnRmgGa0ZxhnLGc8Z4BkjGmygZyIAoIwqgAFjbXAAUBlTGVgZ9SF0ZfVhbQBhAOSgswM6FgCghipyImV2ZQAfYQABaXliGWUZcgBjAB1hM2RvAHQAIWGAoWUibHFzAMYEcBl6GfGhZSLOBAAAdhlsAGEAbgD0AN8EgKF+KmNkbACBGYQZjBljAACgqSpvAHQAb6CAKmyggioAoIQqZeDbIgD+cwAAoJQqcgAA4DXYJN3noGsirATtIWVsAKA3IWMAeQBTZIChdyJFYWoApxmpGasZAKCSKgCgpSoAoKQqAAJFYWVztBm2Gb0ZwhkAoGkicABwoIoq8iFveACgiipxoIgq8aCIKrUZaQBtAACg5yJwAGYAAOA12FjdYQB2AOUAYwIAAWNp0xnWGXIAAKAKIW0AAKFzImVs3BneGQCgjioAoJAqAIM+ADtjZGxxco0E6xn0GfgZ/BkBGgABY2nvGfEZAKCnKnIAAKB6Km8AdAAAoNci0CFhcgCglSl1ImVzdAAAoHwqgAJhZGVscwAKGvQZFhrVBCAa8AEPGgAAFBpwAHIAbwD4AFkZcgAAoHgpcQAAAWxxxAQbGmwAZQBzAPMASRlpAO0A5AQAAWVuJxouGnIjdG5lcXEAAOBpIgD+xQAsGgAFQWFiY2Vma29zeUAaQxpmGmoabRqDGocalhrCGtMacgDyAMwCAAJpbG1yShpOGlAaVBpyAHMA8ABxD2YAvWBpAGwA9AASBQABZHJYGlsaYwB5AEpkAKGUIWN3YBpkGmkAcgAAoEgpAKCtIWEAcgAAoA8h6SFyYyVhgAFhbHIAcxp7Gn8a8iF0c3WgZSZpAHQAAKBlJuwhaXAAoCYg4yFvbgCguSJyAADgNdgl3XMAAAFld4wakRphInJvdwAAoCUpYSJyb3cAAKAmKYACYW1vcHIAnxqjGqcauhq+GnIAcgAAoP8h9CFodACgOyJrAAABbHKsGrMaZSRmdGFycm93AACgqSHpJGdodGFycm93AKCqIWYAAOA12Fnd4iFhcgCgFSCAAWNsdADIGswa0BpyAADgNdi93GEAcwDoAGka8iFvaydhAAFicNca2xr1IWxsAKBDIOghZW4AoBAg4Qr2GgAA/RoAAAgbExsaGwAAIRs7GwAAAAA+G2IbmRuVG6sbAACyG80b0htjAHUAdABlADuA7QDtQAChYyBpeQEbBhtyAGMAO4DuAO5AOGQAAWN4CxsNG3kANWRjAGwAO4ChAKFAAAFmcssCFhsA4DXYJt1yAGEAdgBlADuA7ADsQIChSCFpbm8AJxsyGzYbAAFpbisbLxtuAHQAAKAMKnQAAKAtIuYhaW4AoNwpdABhAACgKSHsIWlnM2GAAWFvcABDG1sbXhuAAWNndABJG0sbWRtyACthgAFlbHAAcQVRG1UbaQBuAOUAyAVhAHIA9AByBWgAMWFmAACgtyJlAGQAtWEAoggiY2ZvdGkbbRt1G3kb4SFyZQCgBSFpAG4AdKAeImkAZQAAoN0pZABvAPQAWxsAoisiY2VscIEbhRuPG5QbYQBsAACguiIAAWdyiRuNG2UAcgDzACMQ4wCCG2EicmhrAACgFyryIW9kAKA8KgACY2dwdJ8boRukG6gbeQBRZG8AbgAvYWYAAOA12FrdYQC5Y3UAZQBzAHQAO4C/AL9AAAFjabUbuRtyAADgNdi+3G4AAKIIIkVkc3bCG8QbyBvQAwCg+SJvAHQAAKD1Inag9CIAoPMiaaBiIOwhZGUpYesB1hsAANkbYwB5AFZkbAA7gO8A70AAA2NmbW9zdeYb7hvyG/Ub+hsFHAABaXnqG+0bcgBjADVhOWRyAADgNdgn3eEhdGg3YnAAZgAA4DXYW93jAf8bAAADHHIAAOA12L/c8iFjeVhk6yFjeVRkAARhY2ZnaGpvcxUcGhwiHCYcKhwtHDAcNRzwIXBhdqC6A/BjAAFleR4cIRzkIWlsN2E6ZHIAAOA12CjdciJlZW4AOGFjAHkARWRjAHkAXGRwAGYAAOA12FzdYwByAADgNdjA3IALQUJFSGFiY2RlZmdoamxtbm9wcnN0dXYAXhxtHHEcdRx5HN8cBx0dHTwd3B3tHfEdAR4EHh0eLB5FHrwewx7hHgkfPR9LH4ABYXJ0AGQcZxxpHHIA8gBvB/IAxQLhIWlsAKAbKeEhcnIAoA4pZ6BmIgCgiyphAHIAAKBiKWMJjRwAAJAcAACVHAAAAAAAAAAAAACZHJwcAACmHKgcrRwAANIc9SF0ZTph7SJwdHl2AKC0KXIAYQDuAFoG4iFkYbtjZwAAoegnZGyhHKMcAKCRKeUAiwYAoIUqdQBvADuAqwCrQHIAgKOQIWJmaGxwc3QAuhy/HMIcxBzHHMoczhxmoOQhcwAAoB8pcwAAoB0p6wCyGnAAAKCrIWwAAKA5KWkAbQAAoHMpbAAAoKIhAKGrKmFl1hzaHGkAbAAAoBkpc6CtKgDgrSoA/oABYWJyAOUc6RztHHIAcgAAoAwpcgBrAACgcicAAWFr8Rz4HGMAAAFla/Yc9xx7YFtgAAFlc/wc/hwAoIspbAAAAWR1Ax0FHQCgjykAoI0pAAJhZXV5Dh0RHRodHB3yIW9uPmEAAWRpFR0YHWkAbAA8YewAowbiAPccO2QAAmNxcnMkHScdLB05HWEAAKA2KXUAbwDyoBwgqhEAAWR1MB00HeghYXIAoGcpcyJoYXIAAKBLKWgAAKCyIQCiZCJmZ3FzRB1FB5Qdnh10AIACYWhscnQATh1WHWUdbB2NHXIicm93AHSgkCFhAOkAzxxhI3Jwb29uAAABZHVeHWId7yF3bgCgvSFwAACgvCHlJGZ0YXJyb3dzAKDHIWkiZ2h0AIABYWhzAHUdex2DHXIicm93APOglCGdBmEAcgBwAG8AbwBuAPMAzgtxAHUAaQBnAGEAcgByAG8A9wBlGugkcmVldGltZXMAoMsi8aFkIk0HAACaHWwAYQBuAPQAXgcAon0qY2Rnc6YdqR2xHbcdYwAAoKgqbwB0AG+gfypyoIEqAKCDKmXg2iIA/nMAAKCTKoACYWRlZ3MAwB3GHcod1h3ZHXAAcAByAG8A+ACmHG8AdAAAoNYicQAAAWdxzx3SHXQA8gBGB2cAdADyAHQcdADyAFMHaQDtAGMHgAFpbHIA4h3mHeod8yFodACgfClvAG8A8gDKBgDgNdgp3UWgdiIAoJEqYQH1Hf4dcgAAAWR1YB35HWygvCEAoGopbABrAACghCVjAHkAWWQAomoiYWNodAweDx4VHhkecgDyAGsdbwByAG4AZQDyAGAW4SFyZACgaylyAGkAAKD6JQABaW8hHiQe5CFvdEBh9SFzdGGgsCPjIWhlAKCwIwACRWFlczMeNR48HkEeAKBoInAAcKCJKvIhb3gAoIkqcaCHKvGghyo0HmkAbQAAoOYiAARhYm5vcHR3elIeXB5fHoUelh6mHqsetB4AAW5yVh5ZHmcAAKDsJ3IAAKD9IXIA6wCwBmcAgAFsbXIAZh52Hnse5SFmdAABYXKIB2weaQBnAGgAdABhAHIAcgBvAPcAkwfhInBzdG8AoPwnaQBnAGgAdABhAHIAcgBvAPcAmgdwI2Fycm93AAABbHKNHpEeZQBmAPQAxhxpImdodAAAoKwhgAFhZmwAnB6fHqIecgAAoIUpAOA12F3ddQBzAACgLSppIm1lcwAAoDQqYQGvHrMecwB0AACgFyLhAIoOZaHKJbkeRhLuIWdlAKDKJWEAcgBsoCgAdAAAoJMpgAJhY2htdADMHs8e1R7bHt0ecgDyAJ0GbwByAG4AZQDyANYWYQByAGSgyyEAoG0pAKAOIHIAaQAAoL8iAANhY2hpcXTrHu8e1QfzHv0eBh/xIXVvAKA5IHIAAOA12MHcbQDloXIi+h4AAPweAKCNKgCgjyoAAWJ19xwBH28AcqAYIACgGiDyIW9rQmEAhDwAO2NkaGlscXJCBhcfxh0gHyQfKB8sHzEfAAFjaRsfHR8AoKYqcgAAoHkqcgBlAOUAkx3tIWVzAKDJIuEhcnIAoHYpdSJlc3QAAKB7KgABUGk1HzkfYQByAACglillocMlAgdfEnIAAAFkdUIfRx9zImhhcgAAoEop6CFhcgCgZikAAWVuTx9WH3IjdG5lcXEAAOBoIgD+xQBUHwAHRGFjZGVmaGlsbm9wc3VuH3Ifoh+rH68ftx+7H74f5h/uH/MfBwj/HwsgxCFvdACgOiIAAmNscHJ5H30fiR+eH3IAO4CvAK9AAAFldIEfgx8AoEImZaAgJ3MAZQAAoCAnc6CmIXQAbwCAoaYhZGx1AJQfmB+cH28AdwDuAHkDZQBmAPQA6gbwAOkO6yFlcgCgriUAAW95ph+qH+0hbWEAoCkqPGThIXNoAKAUIOElc3VyZWRhbmdsZQCgISJyAADgNdgq3W8AAKAnIYABY2RuAMQfyR/bH3IAbwA7gLUAtUBhoiMi0B8AANMf1x9zAPQAKxFpAHIAAKDwKm8AdAA7gLcAt0B1AHMA4qESIh4TAADjH3WgOCIAoCoqYwHqH+0fcAAAoNsq8gB+GnAAbAB1APMACAgAAWRw9x/7H+UhbHMAoKciZgAA4DXYXt0AAWN0AyAHIHIAAOA12MLc8CFvcwCgPiJsobwDECAVIPQiaW1hcACguCJhAPAAEyAADEdMUlZhYmNkZWZnaGlqbG1vcHJzdHV2dzwgRyBmIG0geSCqILgg2iDeIBEhFSEyIUMhTSFQIZwhnyHSIQAiIyKLIrEivyIUIwABZ3RAIEMgAODZIjgD9uBrItIgBwmAAWVsdABNIF8gYiBmAHQAAAFhclMgWCByInJvdwAAoM0h6SRnaHRhcnJvdwCgziEA4NgiOAP24Goi0iBfCekkZ2h0YXJyb3cAoM8hAAFEZHEgdSDhIXNoAKCvIuEhc2gAoK4igAJiY25wdACCIIYgiSCNIKIgbABhAACgByL1IXRlRGFnAADgICLSIACiSSJFaW9wlSCYIJwgniAA4HAqOANkAADgSyI4A3MASWFyAG8A+AAyCnUAcgBhoG4mbADzoG4mmwjzAa8gAACzIHAAO4CgAKBAbQBwAOXgTiI4AyoJgAJhZW91eQDBIMogzSDWINkg8AHGIAAAyCAAoEMqbwBuAEhh5CFpbEZhbgBnAGSgRyJvAHQAAOBtKjgDcAAAoEIqPWThIXNoAKATIACjYCJBYWRxc3jpIO0g+SD+IAIhDCFyAHIAAKDXIXIAAAFocvIg9SBrAACgJClvoJch9wAGD28AdAAA4FAiOAN1AGkA9gC7CAABZWkGIQohYQByAACgKCntAN8I6SFzdPOgBCLlCHIAAOA12CvdAAJFZXN0/wgcISshLiHxoXEiIiEAABMJ8aFxIgAJAAAnIWwAYQBuAPQAEwlpAO0AGQlyoG8iAKBvIoABQWFwADghOyE/IXIA8gBeIHIAcgAAoK4hYQByAACg8ipzogsiSiEAAAAAxwtkoPwiAKD6ImMAeQBaZIADQUVhZGVzdABcIV8hYiFmIWkhkyGWIXIA8gBXIADgZiI4A3IAcgAAoJohcgAAoCUggKFwImZxcwBwIYQhjiF0AAABYXJ1IXohcgByAG8A9wBlIWkAZwBoAHQAYQByAHIAbwD3AD4h8aFwImAhAACKIWwAYQBuAPQAZwlz4H0qOAMAoG4iaQDtAG0JcqBuImkA5aDqIkUJaQDkADoKAAFwdKMhpyFmAADgNdhf3YCBrAA7aW4AriGvIcchrEBuAIChCSJFZHYAtyG6Ib8hAOD5IjgDbwB0AADg9SI4A+EB1gjEIcYhAKD3IgCg9iJpAHagDCLhAagJzyHRIQCg/iIAoP0igAFhb3IA2CHsIfEhcgCAoSYiYXN0AOAh5SHpIWwAbABlAOwAywhsAADg/SrlIADgAiI4A2wiaW50AACgFCrjoYAi9yEAAPohdQDlAJsJY+CvKjgDZaCAIvEAkwkAAkFhaXQHIgoiFyIeInIA8gBsIHIAcgAAoZshY3cRIhQiAOAzKTgDAOCdITgDZyRodGFycm93AACgmyFyAGkA5aDrIr4JgANjaGltcHF1AC8iPCJHIpwhTSJQIloigKGBImNlcgA2Iv0JOSJ1AOUABgoA4DXYw9zvIXJ0bQKdIQAAAABEImEAcgDhAOEhbQBloEEi8aBEIiYKYQDyAMsIcwB1AAABYnBWIlgi5QDUCeUA3wmAAWJjcABgInMieCKAoYQiRWVzAGci7glqIgDgxSo4A2UAdABl4IIi0iBxAPGgiCJoImMAZaCBIvEA/gmAoYUiRWVzAH8iFgqCIgDgxio4A2UAdABl4IMi0iBxAPGgiSKAIgACZ2lscpIilCKaIpwi7AAMCWwAZABlADuA8QDxQOcAWwlpI2FuZ2xlAAABbHKkIqoi5SFmdGWg6iLxAEUJaSJnaHQAZaDrIvEAvgltoL0DAKEjAGVzuCK8InIAbwAAoBYhcAAAoAcggARESGFkZ2lscnMAziLSItYi2iLeIugi7SICIw8j4SFzaACgrSLhIXJyAKAEKXAAAOBNItIg4SFzaACgrCIAAWV04iLlIgDgZSLSIADgPgDSIG4iZmluAACg3imAAUFldADzIvci+iJyAHIAAKACKQDgZCLSIHLgPADSIGkAZQAA4LQi0iAAAUF0BiMKI3IAcgAAoAMp8iFpZQDgtSLSIGkAbQAA4Dwi0iCAAUFhbgAaIx4jKiNyAHIAAKDWIXIAAAFociMjJiNrAACgIylvoJYh9wD/DuUhYXIAoCcpUxJqFAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVCMAAF4jaSN/I4IjjSOeI8AUAAAAAKYjwCMAANoj3yMAAO8jHiQvJD8kRCQAAWNzVyNsFHUAdABlADuA8wDzQAABaXlhI2cjcgBjoJoiO4D0APRAPmSAAmFiaW9zAHEjdCN3I3EBeiNzAOgAdhTsIWFjUWF2AACgOCrvIWxkAKC8KewhaWdTYQABY3KFI4kjaQByAACgvykA4DXYLN1vA5QjAAAAAJYjAACcI24A22JhAHYAZQA7gPIA8kAAoMEpAAFibaEjjAphAHIAAKC1KQACYWNpdKwjryO6I70jcgDyAFkUAAFpcrMjtiNyAACgvinvIXNzAKC7KW4A5QDZCgCgwCmAAWFlaQDFI8gjyyNjAHIATWFnAGEAyWOAAWNkbgDRI9Qj1iPyIW9uv2MAoLYpdQDzAHgBcABmAADgNdhg3YABYWVsAOQj5yPrI3IAAKC3KXIAcAAAoLkpdQDzAHwBAKMoImFkaW9zdvkj/CMPJBMkFiQbJHIA8gBeFIChXSplZm0AAyQJJAwkcgBvoDQhZgAAoDQhO4CqAKpAO4C6ALpA5yFvZgCgtiJyAACgVipsIm9wZQAAoFcqAKBbKoABY2xvACMkJSQrJPIACCRhAHMAaAA7gPgA+EBsAACgmCJpAGwBMyQ4JGQAZQA7gPUA9UBlAHMAYaCXInMAAKA2Km0AbAA7gPYA9kDiIWFyAKA9I+EKXiQAAHokAAB8JJQkAACYJKkkAAAAALUkEQsAAPAkAAAAAAQleiUAAIMlcgCAoSUiYXN0AGUkbyQBCwCBtgA7bGokayS2QGwAZQDsABgDaQJ1JAAAAAB4JG0AAKDzKgCg/Sp5AD9kcgCAAmNpbXB0AIUkiCSLJJkSjyRuAHQAJWBvAGQALmBpAGwAAKAwIOUhbmsAoDEgcgAA4DXYLd2AAWltbwCdJKAkpCR2oMYD1WNtAGEA9AD+B24AZQAAoA4m9KHAA64kAAC0JGMjaGZvcmsAAKDUItZjAAFhdbgkxCRuAAABY2u9JMIkawBooA8hAKAOIfYAaRpzAACkKwBhYmNkZW1zdNMkIRPXJNsk4STjJOck6yTjIWlyAKAjKmkAcgAAoCIqAAFvdYsW3yQAoCUqAKByKm4AO4CxALFAaQBtAACgJip3AG8AAKAnKoABaXB1APUk+iT+JO4idGludACgFSpmAADgNdhh3W4AZAA7gKMAo0CApHoiRWFjZWlub3N1ABMlFSUYJRslTCVRJVklSSV1JQCgsypwAACgtyp1AOUAPwtjoK8qgKJ6ImFjZW5zACclLSU0JTYlSSVwAHAAcgBvAPgAFyV1AHIAbAB5AGUA8QA/C/EAOAuAAWFlcwA8JUElRSXwInByb3gAoLkqcQBxAACgtSppAG0AAKDoImkA7QBEC20AZQDzoDIgIguAAUVhcwBDJVclRSXwAEAlgAFkZnAATwtfJXElgAFhbHMAZSVpJW0l7CFhcgCgLiPpIW5lAKASI/UhcmYAoBMjdKAdIu8AWQvyIWVsAKCwIgABY2l9JYElcgAA4DXYxdzIY24iY3NwAACgCCAAA2Zpb3BzdZElKxuVJZolnyWkJXIAAOA12C7dcABmAADgNdhi3XIiaW1lAACgVyBjAHIAAOA12MbcgAFhZW8AqiW6JcAldAAAAWVpryW2JXIAbgBpAG8AbgDzABkFbgB0AACgFipzAHQAZaA/APEACRj0AG0LgApBQkhhYmNkZWZoaWxtbm9wcnN0dXgA4yXyJfYl+iVpJpAmpia9JtUm5ib4JlonaCdxJ3UnnietJ7EnyCfiJ+cngAFhcnQA6SXsJe4lcgDyAJkM8gD6AuEhaWwAoBwpYQByAPIA3BVhAHIAAKBkKYADY2RlbnFydAAGJhAmEyYYJiYmKyZaJgABZXUKJg0mAOA9IjEDdABlAFVhaQDjACAN7SJwdHl2AKCzKWcAgKHpJ2RlbAAgJiImJCYAoJIpAKClKeUA9wt1AG8AO4C7ALtAcgAApZIhYWJjZmhscHN0dz0mQCZFJkcmSiZMJk4mUSZVJlgmcAAAoHUpZqDlIXMAAKAgKQCgMylzAACgHinrALka8ACVHmwAAKBFKWkAbQAAoHQpbAAAoKMhAKCdIQABYWleJmImaQBsAACgGilvAG6gNiJhAGwA8wB2C4ABYWJyAG8mciZ2JnIA8gAvEnIAawAAoHMnAAFha3omgSZjAAABZWt/JoAmfWBdYAABZXOFJocmAKCMKWwAAAFkdYwmjiYAoI4pAKCQKQACYWV1eZcmmiajJqUm8iFvbllhAAFkaZ4moSZpAGwAV2HsAA8M4gCAJkBkAAJjbHFzrSawJrUmuiZhAACgNylkImhhcgAAoGkpdQBvAPKgHSCjAWgAAKCzIYABYWNnAMMm0iaUC2wAgKEcIWlwcwDLJs4migxuAOUAoAxhAHIA9ADaC3QAAKCtJYABaWxyANsm3ybjJvMhaHQAoH0pbwBvAPIANgwA4DXYL90AAWFv6ib1JnIAAAFkde8m8SYAoMEhbKDAIQCgbCl2oMED8WOAAWducwD+Jk4nUCdoAHQAAANhaGxyc3QKJxInISc1Jz0nRydyInJvdwB0oJIhYQDpAFYmYSNycG9vbgAAAWR1GiceJ28AdwDuAPAmcAAAoMAh5SFmdAABYWgnJy0ncgByAG8AdwDzAAkMYQByAHAAbwBvAG4A8wATBGklZ2h0YXJyb3dzAACgySFxAHUAaQBnAGEAcgByAG8A9wBZJugkcmVldGltZXMAoMwiZwDaYmkAbgBnAGQAbwB0AHMAZQDxABwYgAFhaG0AYCdjJ2YncgDyAAkMYQDyABMEAKAPIG8idXN0AGGgsSPjIWhlAKCxI+0haWQAoO4qAAJhYnB0fCeGJ4knmScAAW5ygCeDJ2cAAKDtJ3IAAKD+IXIA6wAcDIABYWZsAI8nkieVJ3IAAKCGKQDgNdhj3XUAcwAAoC4qaSJtZXMAAKA1KgABYXCiJ6gncgBnoCkAdAAAoJQp7yJsaW50AKASKmEAcgDyADwnAAJhY2hxuCe8J6EMwCfxIXVvAKA6IHIAAOA12MfcAAFidYAmxCdvAPKgGSCoAYABaGlyAM4n0ifWJ3IAZQDlAE0n7SFlcwCgyiJpAIChuSVlZmwAXAxjEt4n9CFyaQCgzinsInVoYXIAoGgpAKAeIWENBSgJKA0oSyhVKIYoAACLKLAoAAAAAOMo5ygAABApJCkxKW0pcSmHKaYpAACYKgAAAACxKmMidXRlAFthcQB1AO8ABR+ApHsiRWFjZWlucHN5ABwoHignKCooLygyKEEoRihJKACgtCrwASMoAAAlKACguCpvAG4AYWF1AOUAgw1koLAqaQBsAF9hcgBjAF1hgAFFYXMAOCg6KD0oAKC2KnAAAKC6KmkAbQAAoOki7yJsaW50AKATKmkA7QCIDUFkbwB0AGKixSKRFgAAAABTKACgZiqAA0FhY21zdHgAYChkKG8ocyh1KHkogihyAHIAAKDYIXIAAAFocmkoayjrAJAab6CYIfcAzAd0ADuApwCnQGkAO2D3IWFyAKApKW0AAAFpbn4ozQBuAHUA8wDOAHQAAKA2J3IA7+A12DDdIxkAAmFjb3mRKJUonSisKHIAcAAAoG8mAAFoeZkonChjAHkASWRIZHIAdABtAqUoAAAAAKgoaQDkAFsPYQByAGEA7ABsJDuArQCtQAABZ22zKLsobQBhAAChwwNmdroouijCY4CjPCJkZWdsbnByAMgozCjPKNMo1yjaKN4obwB0AACgairxoEMiCw5FoJ4qAKCgKkWgnSoAoJ8qZQAAoEYi7CF1cwCgJCrhIXJyAKByKWEAcgDyAPwMAAJhZWl07Sj8KAEpCCkAAWxz8Sj4KGwAcwBlAHQAbQDpAH8oaABwAACgMyrwImFyc2wAoOQpAAFkbFoPBSllAACgIyNloKoqc6CsKgDgrCoA/oABZmxwABUpGCkfKfQhY3lMZGKgLwBhoMQpcgAAoD8jZgAA4DXYZN1hAAABZHIoKRcDZQBzAHWgYCZpAHQAAKBgJoABY3N1ADYpRilhKQABYXU6KUApcABzoJMiAOCTIgD+cABzoJQiAOCUIgD+dQAAAWJwSylWKQChjyJlcz4NUCllAHQAZaCPIvEAPw0AoZAiZXNIDVspZQB0AGWgkCLxAEkNAKGhJWFmZilbBHIAZQFrKVwEAKChJWEAcgDyAAMNAAJjZW10dyl7KX8pgilyAADgNdjI3HQAbQDuAM4AaQDsAAYpYQByAOYAVw0AAWFyiimOKXIA5qAGJhESAAFhbpIpoylpImdodAAAAWVwmSmgKXAAcwBpAGwAbwDuANkXaADpAKAkcwCvYIACYmNtbnAArin8KY4NJSooKgCkgiJFZGVtbnByc7wpvinCKcgpzCnUKdgp3CkAoMUqbwB0AACgvSpkoIYibwB0AACgwyr1IWx0AKDBKgABRWXQKdIpAKDLKgCgiiLsIXVzAKC/KuEhcnIAoHkpgAFlaXUA4inxKfQpdAAAoYIiZW7oKewpcQDxoIYivSllAHEA8aCKItEpbQAAoMcqAAFicPgp+ikAoNUqAKDTKmMAgKJ7ImFjZW5zAAcqDSoUKhYqRihwAHAAcgBvAPgAIyh1AHIAbAB5AGUA8QCDDfEAfA2AAWFlcwAcKiIqPShwAHAAcgBvAPgAPChxAPEAOShnAACgaiYApoMiMTIzRWRlaGxtbnBzPCo/KkIqRSpHKlIqWCpjKmcqaypzKncqO4C5ALlAO4CyALJAO4CzALNAAKDGKgABb3NLKk4qdAAAoL4qdQBiAACg2CpkoIcibwB0AACgxCpzAAABb3VdKmAqbAAAoMknYgAAoNcq4SFycgCgeyn1IWx0AKDCKgABRWVvKnEqAKDMKgCgiyLsIXVzAKDAKoABZWl1AH0qjCqPKnQAAKGDImVugyqHKnEA8aCHIkYqZQBxAPGgiyJwKm0AAKDIKgABYnCTKpUqAKDUKgCg1iqAAUFhbgCdKqEqrCpyAHIAAKDZIXIAAAFocqYqqCrrAJUab6CZIfcAxQf3IWFyAKAqKWwAaQBnADuA3wDfQOELzyrZKtwq6SrsKvEqAAD1KjQrAAAAAAAAAAAAAEwrbCsAAHErvSsAAAAAAADRK3IC1CoAAAAA2CrnIWV0AKAWI8RjcgDrAOUKgAFhZXkA4SrkKucq8iFvbmVh5CFpbGNhQmRvAPQAIg5sInJlYwAAoBUjcgAA4DXYMd0AAmVpa2/7KhIrKCsuK/IBACsAAAkrZQAAATRm6g0EK28AcgDlAOsNYQBzorgDECsAAAAAEit5AG0A0WMAAWNuFislK2sAAAFhcxsrIStwAHAAcgBvAPgAFw5pAG0AAKA8InMA8AD9DQABYXMsKyEr8AAXDnIAbgA7gP4A/kDsATgrOyswG2QA5QBnAmUAcwCAgdcAO2JkAEMrRCtJK9dAYaCgInIAAKAxKgCgMCqAAWVwcwBRK1MraSvhAAkh4qKkIlsrXysAAAAAYytvAHQAAKA2I2kAcgAAoPEqb+A12GXdcgBrAACg2irhAHgociJpbWUAAKA0IIABYWlwAHYreSu3K2QA5QC+DYADYWRlbXBzdACFK6MrmiunK6wrsCuzK24iZ2xlAACitSVkbHFykCuUK5ornCvvIXduAKC/JeUhZnRloMMl8QACBwCgXCJpImdodABloLkl8QBdDG8AdAAAoOwlaSJudXMAAKA6KuwhdXMAoDkqYgAAoM0p6SFtZQCgOyrlInppdW0AoOIjgAFjaHQAwivKK80rAAFyecYrySsA4DXYydxGZGMAeQBbZPIhb2tnYQABaW/UK9creAD0ANERaCJlYWQAAAFsct4r5ytlAGYAdABhAHIAcgBvAPcAXQbpJGdodGFycm93AKCgIQAJQUhhYmNkZmdobG1vcHJzdHV3CiwNLBEsHSwnLDEsQCxLLFIsYix6LIQsjyzLLOgs7Sz/LAotcgDyAAkDYQByAACgYykAAWNyFSwbLHUAdABlADuA+gD6QPIACQ1yAOMBIywAACUseQBeZHYAZQBtYQABaXkrLDAscgBjADuA+wD7QENkgAFhYmgANyw6LD0scgDyANEO7CFhY3FhYQDyAOAOAAFpckQsSCzzIWh0AKB+KQDgNdgy3XIAYQB2AGUAO4D5APlAYQFWLF8scgAAAWxyWixcLACgvyEAoL4hbABrAACggCUAAWN0Zix2LG8CbCwAAAAAcyxyAG4AZaAcI3IAAKAcI28AcAAAoA8jcgBpAACg+CUAAWFsfiyBLGMAcgBrYTuAqACoQAABZ3CILIssbwBuAHNhZgAA4DXYZt0AA2FkaGxzdZksniynLLgsuyzFLHIAcgBvAPcACQ1vAHcAbgBhAHIAcgBvAPcA2A5hI3Jwb29uAAABbHKvLLMsZQBmAPQAWyxpAGcAaAD0AF0sdQDzAKYOaQAAocUDaGzBLMIs0mNvAG4AxWPwI2Fycm93cwCgyCGAAWNpdADRLOEs5CxvAtcsAAAAAN4scgBuAGWgHSNyAACgHSNvAHAAAKAOI24AZwBvYXIAaQAAoPklYwByAADgNdjK3IABZGlyAPMs9yz6LG8AdAAAoPAi7CFkZWlhaQBmoLUlAKC0JQABYW0DLQYtcgDyAMosbAA7gPwA/EDhIm5nbGUAoKcpgAdBQkRhY2RlZmxub3Byc3oAJy0qLTAtNC2bLZ0toS2/LcMtxy3TLdgt3C3gLfwtcgDyABADYQByAHag6CoAoOkqYQBzAOgA/gIAAW5yOC08LechcnQAoJwpgANla25wcnN0AJkpSC1NLVQtXi1iLYItYQBwAHAA4QAaHG8AdABoAGkAbgDnAKEXgAFoaXIAoSmzJFotbwBwAPQAdCVooJUh7wD4JgABaXVmLWotZwBtAOEAuygAAWJwbi14LXMjZXRuZXEAceCKIgD+AODLKgD+cyNldG5lcQBx4IsiAP4A4MwqAP4AAWhyhi2KLWUAdADhABIraSNhbmdsZQAAAWxyki2WLeUhZnQAoLIiaSJnaHQAAKCzInkAMmThIXNoAKCiIoABZWxyAKcttC24LWKiKCKuLQAAAACyLWEAcgAAoLsicQAAoFoi7CFpcACg7iIAAWJ0vC1eD2EA8gBfD3IAAOA12DPddAByAOkAlS1zAHUAAAFicM0t0C0A4IIi0iAA4IMi0iBwAGYAAOA12GfdcgBvAPAAWQt0AHIA6QCaLQABY3XkLegtcgAA4DXYy9wAAWJw7C30LW4AAAFFZXUt8S0A4IoiAP5uAAABRWV/LfktAOCLIgD+6SJnemFnAKCaKYADY2Vmb3BycwANLhAuJS4pLiMuLi40LukhcmN1YQABZGkULiEuAAFiZxguHC5hAHIAAKBfKmUAcaAnIgCgWSLlIXJwAKAYIXIAAOA12DTdcABmAADgNdho3WWgQCJhAHQA6ABqD2MAcgAA4DXYzNzjCuQRUC4AAFQuAABYLmIuAAAAAGMubS5wLnQuAAAAAIguki4AAJouJxIqEnQAcgDpAB0ScgAA4DXYNd0AAUFhWy5eLnIA8gDnAnIA8gCTB75jAAFBYWYuaS5yAPIA4AJyAPIAjAdhAPAAeh5pAHMAAKD7IoABZHB0APgReS6DLgABZmx9LoAuAOA12GnddQDzAP8RaQBtAOUABBIAAUFhiy6OLnIA8gDuAnIA8gCaBwABY3GVLgoScgAA4DXYzdwAAXB0nS6hLmwAdQDzACUScgDpACASAARhY2VmaW9zdbEuvC7ELsguzC7PLtQu2S5jAAABdXm2LrsudABlADuA/QD9QE9kAAFpecAuwy5yAGMAd2FLZG4AO4ClAKVAcgAA4DXYNt1jAHkAV2RwAGYAAOA12GrdYwByAADgNdjO3AABY23dLt8ueQBOZGwAO4D/AP9AAAVhY2RlZmhpb3N38y73Lv8uAi8MLxAvEy8YLx0vIi9jInV0ZQB6YQABYXn7Lv4u8iFvbn5hN2RvAHQAfGEAAWV0Bi8KL3QAcgDmAB8QYQC2Y3IAAOA12DfdYwB5ADZk5yJyYXJyAKDdIXAAZgAA4DXYa91jAHIAAOA12M/cAAFqbiYvKC8AoA0gagAAoAwg");

// ../imp-pinned/node_modules/entities/dist/generated/decode-data-xml.js
var xmlDecodeTree = /* @__PURE__ */ decodeBase64("AAJhZ2xxBwARABMAFQBtAg0AAAAAAA8AcAAmYG8AcwAnYHQAPmB0ADxg9SFvdCJg");

// ../imp-pinned/node_modules/entities/dist/internal/bin-trie-flags.js
var BinTrieFlags;
(function(BinTrieFlags2) {
  BinTrieFlags2[BinTrieFlags2["VALUE_LENGTH"] = 49152] = "VALUE_LENGTH";
  BinTrieFlags2[BinTrieFlags2["FLAG13"] = 8192] = "FLAG13";
  BinTrieFlags2[BinTrieFlags2["BRANCH_LENGTH"] = 8064] = "BRANCH_LENGTH";
  BinTrieFlags2[BinTrieFlags2["JUMP_TABLE"] = 127] = "JUMP_TABLE";
})(BinTrieFlags || (BinTrieFlags = {}));

// ../imp-pinned/node_modules/entities/dist/decode.js
var CharCodes;
(function(CharCodes2) {
  CharCodes2[CharCodes2["NUM"] = 35] = "NUM";
  CharCodes2[CharCodes2["SEMI"] = 59] = "SEMI";
  CharCodes2[CharCodes2["EQUALS"] = 61] = "EQUALS";
  CharCodes2[CharCodes2["ZERO"] = 48] = "ZERO";
  CharCodes2[CharCodes2["NINE"] = 57] = "NINE";
  CharCodes2[CharCodes2["LOWER_A"] = 97] = "LOWER_A";
  CharCodes2[CharCodes2["LOWER_F"] = 102] = "LOWER_F";
  CharCodes2[CharCodes2["LOWER_X"] = 120] = "LOWER_X";
  CharCodes2[CharCodes2["LOWER_Z"] = 122] = "LOWER_Z";
  CharCodes2[CharCodes2["UPPER_A"] = 65] = "UPPER_A";
  CharCodes2[CharCodes2["UPPER_F"] = 70] = "UPPER_F";
  CharCodes2[CharCodes2["UPPER_Z"] = 90] = "UPPER_Z";
})(CharCodes || (CharCodes = {}));
var TO_LOWER_BIT = 32;
function isNumber(code) {
  return code >= CharCodes.ZERO && code <= CharCodes.NINE;
}
function isHexadecimalCharacter(code) {
  return code >= CharCodes.UPPER_A && code <= CharCodes.UPPER_F || code >= CharCodes.LOWER_A && code <= CharCodes.LOWER_F;
}
function isAsciiAlphaNumeric(code) {
  return code >= CharCodes.UPPER_A && code <= CharCodes.UPPER_Z || code >= CharCodes.LOWER_A && code <= CharCodes.LOWER_Z || isNumber(code);
}
function isEntityInAttributeInvalidEnd(code) {
  return code === CharCodes.EQUALS || isAsciiAlphaNumeric(code);
}
var EntityDecoderState;
(function(EntityDecoderState2) {
  EntityDecoderState2[EntityDecoderState2["EntityStart"] = 0] = "EntityStart";
  EntityDecoderState2[EntityDecoderState2["NumericStart"] = 1] = "NumericStart";
  EntityDecoderState2[EntityDecoderState2["NumericDecimal"] = 2] = "NumericDecimal";
  EntityDecoderState2[EntityDecoderState2["NumericHex"] = 3] = "NumericHex";
  EntityDecoderState2[EntityDecoderState2["NamedEntity"] = 4] = "NamedEntity";
})(EntityDecoderState || (EntityDecoderState = {}));
var DecodingMode;
(function(DecodingMode2) {
  DecodingMode2[DecodingMode2["Legacy"] = 0] = "Legacy";
  DecodingMode2[DecodingMode2["Strict"] = 1] = "Strict";
  DecodingMode2[DecodingMode2["Attribute"] = 2] = "Attribute";
})(DecodingMode || (DecodingMode = {}));

class EntityDecoder {
  decodeTree;
  emitCodePoint;
  errors;
  constructor(decodeTree, emitCodePoint, errors) {
    this.decodeTree = decodeTree;
    this.emitCodePoint = emitCodePoint;
    this.errors = errors;
  }
  state = EntityDecoderState.EntityStart;
  consumed = 1;
  result = 0;
  treeIndex = 0;
  excess = 1;
  decodeMode = DecodingMode.Strict;
  runConsumed = 0;
  startEntity(decodeMode) {
    this.decodeMode = decodeMode;
    this.state = EntityDecoderState.EntityStart;
    this.result = 0;
    this.treeIndex = 0;
    this.excess = 1;
    this.consumed = 1;
    this.runConsumed = 0;
  }
  write(input, offset) {
    switch (this.state) {
      case EntityDecoderState.EntityStart: {
        if (input.charCodeAt(offset) === CharCodes.NUM) {
          this.state = EntityDecoderState.NumericStart;
          this.consumed += 1;
          return this.stateNumericStart(input, offset + 1);
        }
        this.state = EntityDecoderState.NamedEntity;
        return this.stateNamedEntity(input, offset);
      }
      case EntityDecoderState.NumericStart: {
        return this.stateNumericStart(input, offset);
      }
      case EntityDecoderState.NumericDecimal: {
        return this.stateNumericDecimal(input, offset);
      }
      case EntityDecoderState.NumericHex: {
        return this.stateNumericHex(input, offset);
      }
      case EntityDecoderState.NamedEntity: {
        return this.stateNamedEntity(input, offset);
      }
    }
  }
  stateNumericStart(input, offset) {
    if (offset >= input.length) {
      return -1;
    }
    if ((input.charCodeAt(offset) | TO_LOWER_BIT) === CharCodes.LOWER_X) {
      this.state = EntityDecoderState.NumericHex;
      this.consumed += 1;
      return this.stateNumericHex(input, offset + 1);
    }
    this.state = EntityDecoderState.NumericDecimal;
    return this.stateNumericDecimal(input, offset);
  }
  stateNumericHex(input, offset) {
    while (offset < input.length) {
      const char = input.charCodeAt(offset);
      if (isNumber(char) || isHexadecimalCharacter(char)) {
        const digit = char <= CharCodes.NINE ? char - CharCodes.ZERO : (char | TO_LOWER_BIT) - CharCodes.LOWER_A + 10;
        this.result = this.result * 16 + digit;
        this.consumed++;
        offset++;
      } else {
        return this.emitNumericEntity(char, 3);
      }
    }
    return -1;
  }
  stateNumericDecimal(input, offset) {
    while (offset < input.length) {
      const char = input.charCodeAt(offset);
      if (isNumber(char)) {
        this.result = this.result * 10 + (char - CharCodes.ZERO);
        this.consumed++;
        offset++;
      } else {
        return this.emitNumericEntity(char, 2);
      }
    }
    return -1;
  }
  emitNumericEntity(lastCp, expectedLength) {
    if (this.consumed <= expectedLength) {
      this.errors?.absenceOfDigitsInNumericCharacterReference(this.consumed);
      return 0;
    }
    if (lastCp === CharCodes.SEMI) {
      this.consumed += 1;
    } else if (this.decodeMode === DecodingMode.Strict) {
      return 0;
    }
    this.emitCodePoint(replaceCodePoint(this.result), this.consumed);
    if (this.errors) {
      if (lastCp !== CharCodes.SEMI) {
        this.errors.missingSemicolonAfterCharacterReference();
      }
      this.errors.validateNumericCharacterReference(this.result);
    }
    return this.consumed;
  }
  stateNamedEntity(input, offset) {
    const { decodeTree } = this;
    let current = decodeTree[this.treeIndex];
    let valueLength = (current & BinTrieFlags.VALUE_LENGTH) >> 14;
    while (offset < input.length) {
      if (valueLength === 0 && (current & BinTrieFlags.FLAG13) !== 0) {
        const runLength = (current & BinTrieFlags.BRANCH_LENGTH) >> 7;
        if (this.runConsumed === 0) {
          const firstChar = current & BinTrieFlags.JUMP_TABLE;
          if (input.charCodeAt(offset) !== firstChar) {
            return this.result === 0 ? 0 : this.emitNotTerminatedNamedEntity();
          }
          offset++;
          this.excess++;
          this.runConsumed++;
        }
        while (this.runConsumed < runLength) {
          if (offset >= input.length) {
            return -1;
          }
          const charIndexInPacked = this.runConsumed - 1;
          const packedWord = decodeTree[this.treeIndex + 1 + (charIndexInPacked >> 1)];
          const expectedChar = charIndexInPacked % 2 === 0 ? packedWord & 255 : packedWord >> 8 & 255;
          if (input.charCodeAt(offset) !== expectedChar) {
            this.runConsumed = 0;
            return this.result === 0 ? 0 : this.emitNotTerminatedNamedEntity();
          }
          offset++;
          this.excess++;
          this.runConsumed++;
        }
        this.runConsumed = 0;
        this.treeIndex += 1 + (runLength >> 1);
        current = decodeTree[this.treeIndex];
        valueLength = (current & BinTrieFlags.VALUE_LENGTH) >> 14;
      }
      if (offset >= input.length)
        break;
      const char = input.charCodeAt(offset);
      if (char === CharCodes.SEMI && valueLength !== 0 && (current & BinTrieFlags.FLAG13) !== 0) {
        return this.emitNamedEntityData(this.treeIndex, valueLength, this.consumed + this.excess);
      }
      this.treeIndex = determineBranch(decodeTree, current, this.treeIndex + Math.max(1, valueLength), char);
      if (this.treeIndex < 0) {
        return this.result === 0 || this.decodeMode === DecodingMode.Attribute && (valueLength === 0 || isEntityInAttributeInvalidEnd(char)) ? 0 : this.emitNotTerminatedNamedEntity();
      }
      current = decodeTree[this.treeIndex];
      valueLength = (current & BinTrieFlags.VALUE_LENGTH) >> 14;
      if (valueLength !== 0) {
        if (char === CharCodes.SEMI) {
          return this.emitNamedEntityData(this.treeIndex, valueLength, this.consumed + this.excess);
        }
        if (this.decodeMode !== DecodingMode.Strict && (current & BinTrieFlags.FLAG13) === 0) {
          this.result = this.treeIndex;
          this.consumed += this.excess;
          this.excess = 0;
        }
      }
      offset++;
      this.excess++;
    }
    return -1;
  }
  emitNotTerminatedNamedEntity() {
    const { result, decodeTree } = this;
    const valueLength = (decodeTree[result] & BinTrieFlags.VALUE_LENGTH) >> 14;
    this.emitNamedEntityData(result, valueLength, this.consumed);
    this.errors?.missingSemicolonAfterCharacterReference();
    return this.consumed;
  }
  emitNamedEntityData(result, valueLength, consumed) {
    const { decodeTree } = this;
    this.emitCodePoint(valueLength === 1 ? decodeTree[result] & ~(BinTrieFlags.VALUE_LENGTH | BinTrieFlags.FLAG13) : decodeTree[result + 1], consumed);
    if (valueLength === 3) {
      this.emitCodePoint(decodeTree[result + 2], consumed);
    }
    return consumed;
  }
  end() {
    switch (this.state) {
      case EntityDecoderState.NamedEntity: {
        return this.result !== 0 && (this.decodeMode !== DecodingMode.Attribute || this.result === this.treeIndex) ? this.emitNotTerminatedNamedEntity() : 0;
      }
      case EntityDecoderState.NumericDecimal: {
        return this.emitNumericEntity(0, 2);
      }
      case EntityDecoderState.NumericHex: {
        return this.emitNumericEntity(0, 3);
      }
      case EntityDecoderState.NumericStart: {
        this.errors?.absenceOfDigitsInNumericCharacterReference(this.consumed);
        return 0;
      }
      case EntityDecoderState.EntityStart: {
        return 0;
      }
    }
  }
}
function determineBranch(decodeTree, current, nodeIndex, char) {
  const branchCount = (current & BinTrieFlags.BRANCH_LENGTH) >> 7;
  const jumpOffset = current & BinTrieFlags.JUMP_TABLE;
  if (branchCount === 0) {
    return jumpOffset !== 0 && char === jumpOffset ? nodeIndex : -1;
  }
  if (jumpOffset) {
    const value = char - jumpOffset;
    return value < 0 || value >= branchCount ? -1 : decodeTree[nodeIndex + value] - 1;
  }
  const packedKeySlots = branchCount + 1 >> 1;
  let lo = 0;
  let hi = branchCount - 1;
  while (lo <= hi) {
    const mid = lo + hi >>> 1;
    const slot = mid >> 1;
    const packed = decodeTree[nodeIndex + slot];
    const midKey = packed >> (mid & 1) * 8 & 255;
    if (midKey < char) {
      lo = mid + 1;
    } else if (midKey > char) {
      hi = mid - 1;
    } else {
      return decodeTree[nodeIndex + packedKeySlots + mid];
    }
  }
  return -1;
}

// ../imp-pinned/node_modules/htmlparser2/dist/Tokenizer.js
var CharCodes2;
(function(CharCodes3) {
  CharCodes3[CharCodes3["Tab"] = 9] = "Tab";
  CharCodes3[CharCodes3["NewLine"] = 10] = "NewLine";
  CharCodes3[CharCodes3["FormFeed"] = 12] = "FormFeed";
  CharCodes3[CharCodes3["CarriageReturn"] = 13] = "CarriageReturn";
  CharCodes3[CharCodes3["Space"] = 32] = "Space";
  CharCodes3[CharCodes3["ExclamationMark"] = 33] = "ExclamationMark";
  CharCodes3[CharCodes3["Number"] = 35] = "Number";
  CharCodes3[CharCodes3["Amp"] = 38] = "Amp";
  CharCodes3[CharCodes3["SingleQuote"] = 39] = "SingleQuote";
  CharCodes3[CharCodes3["DoubleQuote"] = 34] = "DoubleQuote";
  CharCodes3[CharCodes3["Dash"] = 45] = "Dash";
  CharCodes3[CharCodes3["Slash"] = 47] = "Slash";
  CharCodes3[CharCodes3["Zero"] = 48] = "Zero";
  CharCodes3[CharCodes3["Nine"] = 57] = "Nine";
  CharCodes3[CharCodes3["Semi"] = 59] = "Semi";
  CharCodes3[CharCodes3["Lt"] = 60] = "Lt";
  CharCodes3[CharCodes3["Eq"] = 61] = "Eq";
  CharCodes3[CharCodes3["Gt"] = 62] = "Gt";
  CharCodes3[CharCodes3["Questionmark"] = 63] = "Questionmark";
  CharCodes3[CharCodes3["UpperA"] = 65] = "UpperA";
  CharCodes3[CharCodes3["LowerA"] = 97] = "LowerA";
  CharCodes3[CharCodes3["UpperF"] = 70] = "UpperF";
  CharCodes3[CharCodes3["LowerF"] = 102] = "LowerF";
  CharCodes3[CharCodes3["UpperZ"] = 90] = "UpperZ";
  CharCodes3[CharCodes3["LowerZ"] = 122] = "LowerZ";
  CharCodes3[CharCodes3["LowerX"] = 120] = "LowerX";
  CharCodes3[CharCodes3["OpeningSquareBracket"] = 91] = "OpeningSquareBracket";
})(CharCodes2 || (CharCodes2 = {}));
var State;
(function(State2) {
  State2[State2["Text"] = 1] = "Text";
  State2[State2["BeforeTagName"] = 2] = "BeforeTagName";
  State2[State2["InTagName"] = 3] = "InTagName";
  State2[State2["InSelfClosingTag"] = 4] = "InSelfClosingTag";
  State2[State2["BeforeClosingTagName"] = 5] = "BeforeClosingTagName";
  State2[State2["InClosingTagName"] = 6] = "InClosingTagName";
  State2[State2["AfterClosingTagName"] = 7] = "AfterClosingTagName";
  State2[State2["BeforeAttributeName"] = 8] = "BeforeAttributeName";
  State2[State2["InAttributeName"] = 9] = "InAttributeName";
  State2[State2["AfterAttributeName"] = 10] = "AfterAttributeName";
  State2[State2["BeforeAttributeValue"] = 11] = "BeforeAttributeValue";
  State2[State2["InAttributeValueDq"] = 12] = "InAttributeValueDq";
  State2[State2["InAttributeValueSq"] = 13] = "InAttributeValueSq";
  State2[State2["InAttributeValueNq"] = 14] = "InAttributeValueNq";
  State2[State2["BeforeDeclaration"] = 15] = "BeforeDeclaration";
  State2[State2["InDeclaration"] = 16] = "InDeclaration";
  State2[State2["InProcessingInstruction"] = 17] = "InProcessingInstruction";
  State2[State2["BeforeComment"] = 18] = "BeforeComment";
  State2[State2["CDATASequence"] = 19] = "CDATASequence";
  State2[State2["DeclarationSequence"] = 20] = "DeclarationSequence";
  State2[State2["InSpecialComment"] = 21] = "InSpecialComment";
  State2[State2["InCommentLike"] = 22] = "InCommentLike";
  State2[State2["SpecialStartSequence"] = 23] = "SpecialStartSequence";
  State2[State2["InSpecialTag"] = 24] = "InSpecialTag";
  State2[State2["InPlainText"] = 25] = "InPlainText";
  State2[State2["InEntity"] = 26] = "InEntity";
})(State || (State = {}));
function isWhitespace(c) {
  return c === CharCodes2.Space || c === CharCodes2.NewLine || c === CharCodes2.Tab || c === CharCodes2.FormFeed || c === CharCodes2.CarriageReturn;
}
function isEndOfTagSection(c) {
  return c === CharCodes2.Slash || c === CharCodes2.Gt || isWhitespace(c);
}
function isASCIIAlpha(c) {
  return c >= CharCodes2.LowerA && c <= CharCodes2.LowerZ || c >= CharCodes2.UpperA && c <= CharCodes2.UpperZ;
}
var QuoteType;
(function(QuoteType2) {
  QuoteType2[QuoteType2["NoValue"] = 0] = "NoValue";
  QuoteType2[QuoteType2["Unquoted"] = 1] = "Unquoted";
  QuoteType2[QuoteType2["Single"] = 2] = "Single";
  QuoteType2[QuoteType2["Double"] = 3] = "Double";
})(QuoteType || (QuoteType = {}));
var Sequences = {
  Empty: new Uint8Array(0),
  Cdata: new Uint8Array([67, 68, 65, 84, 65, 91]),
  CdataEnd: new Uint8Array([93, 93, 62]),
  CommentEnd: new Uint8Array([45, 45, 33, 62]),
  Doctype: new Uint8Array([100, 111, 99, 116, 121, 112, 101]),
  IframeEnd: new Uint8Array([60, 47, 105, 102, 114, 97, 109, 101]),
  NoembedEnd: new Uint8Array([
    60,
    47,
    110,
    111,
    101,
    109,
    98,
    101,
    100
  ]),
  NoframesEnd: new Uint8Array([
    60,
    47,
    110,
    111,
    102,
    114,
    97,
    109,
    101,
    115
  ]),
  Plaintext: new Uint8Array([
    60,
    47,
    112,
    108,
    97,
    105,
    110,
    116,
    101,
    120,
    116
  ]),
  ScriptEnd: new Uint8Array([60, 47, 115, 99, 114, 105, 112, 116]),
  StyleEnd: new Uint8Array([60, 47, 115, 116, 121, 108, 101]),
  TitleEnd: new Uint8Array([60, 47, 116, 105, 116, 108, 101]),
  TextareaEnd: new Uint8Array([
    60,
    47,
    116,
    101,
    120,
    116,
    97,
    114,
    101,
    97
  ]),
  XmpEnd: new Uint8Array([60, 47, 120, 109, 112])
};
var specialStartSequences = new Map([
  [Sequences.IframeEnd[2], Sequences.IframeEnd],
  [Sequences.NoembedEnd[2], Sequences.NoembedEnd],
  [Sequences.Plaintext[2], Sequences.Plaintext],
  [Sequences.ScriptEnd[2], Sequences.ScriptEnd],
  [Sequences.TitleEnd[2], Sequences.TitleEnd],
  [Sequences.XmpEnd[2], Sequences.XmpEnd]
]);

class Tokenizer {
  cbs;
  state = State.Text;
  buffer = "";
  sectionStart = 0;
  index = 0;
  entityStart = 0;
  baseState = State.Text;
  isSpecial = false;
  running = true;
  offset = 0;
  xmlMode;
  decodeEntities;
  recognizeSelfClosing;
  entityDecoder;
  constructor({ xmlMode = false, decodeEntities = true, recognizeSelfClosing = xmlMode }, cbs) {
    this.cbs = cbs;
    this.xmlMode = xmlMode;
    this.decodeEntities = decodeEntities;
    this.recognizeSelfClosing = recognizeSelfClosing;
    this.entityDecoder = new EntityDecoder(xmlMode ? xmlDecodeTree : htmlDecodeTree, (cp, consumed) => this.emitCodePoint(cp, consumed));
  }
  reset() {
    this.state = State.Text;
    this.buffer = "";
    this.sectionStart = 0;
    this.index = 0;
    this.baseState = State.Text;
    this.isSpecial = false;
    this.currentSequence = Sequences.Empty;
    this.sequenceIndex = 0;
    this.running = true;
    this.offset = 0;
  }
  write(chunk) {
    this.offset += this.buffer.length;
    this.buffer = chunk;
    this.parse();
  }
  end() {
    if (this.running)
      this.finish();
  }
  pause() {
    this.running = false;
  }
  resume() {
    this.running = true;
    if (this.index < this.buffer.length + this.offset) {
      this.parse();
    }
  }
  stateText(c) {
    if (c === CharCodes2.Lt || !this.decodeEntities && this.fastForwardTo(CharCodes2.Lt)) {
      if (this.index > this.sectionStart) {
        this.cbs.ontext(this.sectionStart, this.index);
      }
      this.state = State.BeforeTagName;
      this.sectionStart = this.index;
    } else if (this.decodeEntities && c === CharCodes2.Amp) {
      this.startEntity();
    }
  }
  currentSequence = Sequences.Empty;
  sequenceIndex = 0;
  enterTagBody() {
    if (this.currentSequence === Sequences.Plaintext) {
      this.currentSequence = Sequences.Empty;
      this.state = State.InPlainText;
    } else if (this.isSpecial) {
      this.state = State.InSpecialTag;
      this.sequenceIndex = 0;
    } else {
      this.state = State.Text;
    }
  }
  stateSpecialStartSequence(c) {
    const lower = c | 32;
    if (this.sequenceIndex < this.currentSequence.length) {
      if (lower === this.currentSequence[this.sequenceIndex]) {
        this.sequenceIndex++;
        return;
      }
      if (this.sequenceIndex === 3) {
        if (this.currentSequence === Sequences.ScriptEnd && lower === Sequences.StyleEnd[3]) {
          this.currentSequence = Sequences.StyleEnd;
          this.sequenceIndex = 4;
          return;
        }
        if (this.currentSequence === Sequences.TitleEnd && lower === Sequences.TextareaEnd[3]) {
          this.currentSequence = Sequences.TextareaEnd;
          this.sequenceIndex = 4;
          return;
        }
      } else if (this.sequenceIndex === 4 && this.currentSequence === Sequences.NoembedEnd && lower === Sequences.NoframesEnd[4]) {
        this.currentSequence = Sequences.NoframesEnd;
        this.sequenceIndex = 5;
        return;
      }
    } else if (isEndOfTagSection(c)) {
      this.sequenceIndex = 0;
      this.state = State.InTagName;
      this.stateInTagName(c);
      return;
    }
    this.isSpecial = false;
    this.currentSequence = Sequences.Empty;
    this.sequenceIndex = 0;
    this.state = State.InTagName;
    this.stateInTagName(c);
  }
  stateCDATASequence(c) {
    if (c === Sequences.Cdata[this.sequenceIndex]) {
      if (++this.sequenceIndex === Sequences.Cdata.length) {
        this.state = State.InCommentLike;
        this.currentSequence = Sequences.CdataEnd;
        this.sequenceIndex = 0;
        this.sectionStart = this.index + 1;
      }
    } else {
      this.sequenceIndex = 0;
      if (this.xmlMode) {
        this.state = State.InDeclaration;
        this.stateInDeclaration(c);
      } else {
        this.state = State.InSpecialComment;
        this.stateInSpecialComment(c);
      }
    }
  }
  fastForwardTo(c) {
    while (++this.index < this.buffer.length + this.offset) {
      if (this.buffer.charCodeAt(this.index - this.offset) === c) {
        return true;
      }
    }
    this.index = this.buffer.length + this.offset - 1;
    return false;
  }
  emitComment(offset) {
    this.cbs.oncomment(this.sectionStart, this.index, offset);
    this.sequenceIndex = 0;
    this.sectionStart = this.index + 1;
    this.state = State.Text;
  }
  stateInCommentLike(c) {
    if (!this.xmlMode && this.currentSequence === Sequences.CommentEnd && this.sequenceIndex <= 1 && this.index === this.sectionStart + this.sequenceIndex && c === CharCodes2.Gt) {
      this.emitComment(this.sequenceIndex);
    } else if (this.currentSequence === Sequences.CommentEnd && this.sequenceIndex === 2 && c === CharCodes2.Gt) {
      this.emitComment(2);
    } else if (this.currentSequence === Sequences.CommentEnd && this.sequenceIndex === this.currentSequence.length - 1 && c !== CharCodes2.Gt) {
      this.sequenceIndex = Number(c === CharCodes2.Dash);
    } else if (c === this.currentSequence[this.sequenceIndex]) {
      if (++this.sequenceIndex === this.currentSequence.length) {
        if (this.currentSequence === Sequences.CdataEnd) {
          this.cbs.oncdata(this.sectionStart, this.index, 2);
        } else {
          this.cbs.oncomment(this.sectionStart, this.index, 3);
        }
        this.sequenceIndex = 0;
        this.sectionStart = this.index + 1;
        this.state = State.Text;
      }
    } else if (this.sequenceIndex === 0) {
      if (this.fastForwardTo(this.currentSequence[0])) {
        this.sequenceIndex = 1;
      }
    } else if (c !== this.currentSequence[this.sequenceIndex - 1]) {
      this.sequenceIndex = 0;
    }
  }
  isTagStartChar(c) {
    return this.xmlMode ? !isEndOfTagSection(c) : isASCIIAlpha(c);
  }
  stateInSpecialTag(c) {
    if (this.sequenceIndex === this.currentSequence.length) {
      if (isEndOfTagSection(c)) {
        const endOfText = this.index - this.currentSequence.length;
        if (this.sectionStart < endOfText) {
          const actualIndex = this.index;
          this.index = endOfText;
          this.cbs.ontext(this.sectionStart, endOfText);
          this.index = actualIndex;
        }
        this.isSpecial = false;
        this.sectionStart = endOfText + 2;
        this.stateInClosingTagName(c);
        return;
      }
      this.sequenceIndex = 0;
    }
    if ((c | 32) === this.currentSequence[this.sequenceIndex]) {
      this.sequenceIndex += 1;
    } else if (this.sequenceIndex === 0) {
      if (this.currentSequence === Sequences.TitleEnd || this.currentSequence === Sequences.TextareaEnd) {
        if (this.decodeEntities && c === CharCodes2.Amp) {
          this.startEntity();
        }
      } else if (this.fastForwardTo(CharCodes2.Lt)) {
        this.sequenceIndex = 1;
      }
    } else {
      this.sequenceIndex = Number(c === CharCodes2.Lt);
    }
  }
  stateBeforeTagName(c) {
    if (c === CharCodes2.ExclamationMark) {
      this.state = State.BeforeDeclaration;
      this.sectionStart = this.index + 1;
    } else if (c === CharCodes2.Questionmark) {
      if (this.xmlMode) {
        this.state = State.InProcessingInstruction;
        this.sequenceIndex = 0;
        this.sectionStart = this.index + 1;
      } else {
        this.state = State.InSpecialComment;
        this.sectionStart = this.index;
      }
    } else if (this.isTagStartChar(c)) {
      this.sectionStart = this.index;
      const special = this.xmlMode || this.cbs.isInForeignContext?.() ? undefined : specialStartSequences.get(c | 32);
      if (special === undefined) {
        this.state = State.InTagName;
      } else {
        this.isSpecial = true;
        this.currentSequence = special;
        this.sequenceIndex = 3;
        this.state = State.SpecialStartSequence;
      }
    } else if (c === CharCodes2.Slash) {
      this.state = State.BeforeClosingTagName;
    } else {
      this.state = State.Text;
      this.stateText(c);
    }
  }
  stateInTagName(c) {
    if (isEndOfTagSection(c)) {
      this.cbs.onopentagname(this.sectionStart, this.index);
      this.sectionStart = -1;
      this.state = State.BeforeAttributeName;
      this.stateBeforeAttributeName(c);
    }
  }
  stateBeforeClosingTagName(c) {
    if (isWhitespace(c)) {
      if (this.xmlMode) {} else {
        this.state = State.InSpecialComment;
        this.sectionStart = this.index;
      }
    } else if (c === CharCodes2.Gt) {
      this.state = State.Text;
      if (!this.xmlMode) {
        this.sectionStart = this.index + 1;
      }
    } else {
      this.state = this.isTagStartChar(c) ? State.InClosingTagName : State.InSpecialComment;
      this.sectionStart = this.index;
    }
  }
  stateInClosingTagName(c) {
    if (isEndOfTagSection(c)) {
      this.cbs.onclosetag(this.sectionStart, this.index);
      this.sectionStart = -1;
      this.state = State.AfterClosingTagName;
      this.stateAfterClosingTagName(c);
    }
  }
  stateAfterClosingTagName(c) {
    if (c === CharCodes2.Gt || this.fastForwardTo(CharCodes2.Gt)) {
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    }
  }
  stateBeforeAttributeName(c) {
    if (c === CharCodes2.Gt) {
      this.cbs.onopentagend(this.index);
      this.enterTagBody();
      this.sectionStart = this.index + 1;
    } else if (c === CharCodes2.Slash) {
      this.state = State.InSelfClosingTag;
    } else if (!isWhitespace(c)) {
      this.state = State.InAttributeName;
      this.sectionStart = this.index;
    }
  }
  stateInSelfClosingTag(c) {
    if (c === CharCodes2.Gt) {
      this.cbs.onselfclosingtag(this.index);
      this.sectionStart = this.index + 1;
      if (!this.recognizeSelfClosing) {
        this.enterTagBody();
        return;
      }
      this.state = State.Text;
      this.isSpecial = false;
      this.currentSequence = Sequences.Empty;
    } else if (!isWhitespace(c)) {
      this.state = State.BeforeAttributeName;
      this.stateBeforeAttributeName(c);
    }
  }
  stateInAttributeName(c) {
    if (c === CharCodes2.Eq || isEndOfTagSection(c)) {
      this.cbs.onattribname(this.sectionStart, this.index);
      this.sectionStart = this.index;
      this.state = State.AfterAttributeName;
      this.stateAfterAttributeName(c);
    }
  }
  stateAfterAttributeName(c) {
    if (c === CharCodes2.Eq) {
      this.state = State.BeforeAttributeValue;
    } else if (c === CharCodes2.Slash || c === CharCodes2.Gt) {
      this.cbs.onattribend(QuoteType.NoValue, this.sectionStart);
      this.sectionStart = -1;
      this.state = State.BeforeAttributeName;
      this.stateBeforeAttributeName(c);
    } else if (!isWhitespace(c)) {
      this.cbs.onattribend(QuoteType.NoValue, this.sectionStart);
      this.state = State.InAttributeName;
      this.sectionStart = this.index;
    }
  }
  stateBeforeAttributeValue(c) {
    if (c === CharCodes2.DoubleQuote) {
      this.state = State.InAttributeValueDq;
      this.sectionStart = this.index + 1;
    } else if (c === CharCodes2.SingleQuote) {
      this.state = State.InAttributeValueSq;
      this.sectionStart = this.index + 1;
    } else if (!isWhitespace(c)) {
      this.sectionStart = this.index;
      this.state = State.InAttributeValueNq;
      this.stateInAttributeValueNoQuotes(c);
    }
  }
  handleInAttributeValue(c, quote) {
    if (c === quote || !this.decodeEntities && this.fastForwardTo(quote)) {
      this.cbs.onattribdata(this.sectionStart, this.index);
      this.sectionStart = -1;
      this.cbs.onattribend(quote === CharCodes2.DoubleQuote ? QuoteType.Double : QuoteType.Single, this.index + 1);
      this.state = State.BeforeAttributeName;
    } else if (this.decodeEntities && c === CharCodes2.Amp) {
      this.startEntity();
    }
  }
  stateInAttributeValueDoubleQuotes(c) {
    this.handleInAttributeValue(c, CharCodes2.DoubleQuote);
  }
  stateInAttributeValueSingleQuotes(c) {
    this.handleInAttributeValue(c, CharCodes2.SingleQuote);
  }
  stateInAttributeValueNoQuotes(c) {
    if (isWhitespace(c) || c === CharCodes2.Gt) {
      this.cbs.onattribdata(this.sectionStart, this.index);
      this.sectionStart = -1;
      this.cbs.onattribend(QuoteType.Unquoted, this.index);
      this.state = State.BeforeAttributeName;
      this.stateBeforeAttributeName(c);
    } else if (this.decodeEntities && c === CharCodes2.Amp) {
      this.startEntity();
    }
  }
  stateBeforeDeclaration(c) {
    if (c === CharCodes2.OpeningSquareBracket) {
      this.state = State.CDATASequence;
      this.sequenceIndex = 0;
    } else if (this.xmlMode) {
      this.state = c === CharCodes2.Dash ? State.BeforeComment : State.InDeclaration;
    } else if ((c | 32) === Sequences.Doctype[0]) {
      this.state = State.DeclarationSequence;
      this.currentSequence = Sequences.Doctype;
      this.sequenceIndex = 1;
    } else if (c === CharCodes2.Gt) {
      this.cbs.oncomment(this.sectionStart, this.index, 0);
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    } else if (c === CharCodes2.Dash) {
      this.state = State.BeforeComment;
    } else {
      this.state = State.InSpecialComment;
    }
  }
  stateDeclarationSequence(c) {
    if (this.sequenceIndex === this.currentSequence.length) {
      this.state = State.InDeclaration;
      this.stateInDeclaration(c);
    } else if ((c | 32) === this.currentSequence[this.sequenceIndex]) {
      this.sequenceIndex += 1;
    } else if (c === CharCodes2.Gt) {
      this.cbs.oncomment(this.sectionStart, this.index, 0);
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    } else {
      this.state = State.InSpecialComment;
    }
  }
  stateInDeclaration(c) {
    if (c === CharCodes2.Gt || this.fastForwardTo(CharCodes2.Gt)) {
      this.cbs.ondeclaration(this.sectionStart, this.index);
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    }
  }
  stateInProcessingInstruction(c) {
    if (c === CharCodes2.Questionmark) {
      this.sequenceIndex = 1;
    } else if (c === CharCodes2.Gt && this.sequenceIndex === 1) {
      this.cbs.onprocessinginstruction(this.sectionStart, this.index - 1);
      this.sequenceIndex = 0;
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    } else {
      this.sequenceIndex = Number(this.fastForwardTo(CharCodes2.Questionmark));
    }
  }
  stateBeforeComment(c) {
    if (c === CharCodes2.Dash) {
      this.state = State.InCommentLike;
      this.currentSequence = Sequences.CommentEnd;
      this.sequenceIndex = 0;
      this.sectionStart = this.index + 1;
    } else if (this.xmlMode) {
      this.state = State.InDeclaration;
    } else if (c === CharCodes2.Gt) {
      this.cbs.oncomment(this.sectionStart, this.index, 0);
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    } else {
      this.state = State.InSpecialComment;
    }
  }
  stateInSpecialComment(c) {
    if (c === CharCodes2.Gt || this.fastForwardTo(CharCodes2.Gt)) {
      this.cbs.oncomment(this.sectionStart, this.index, 0);
      this.state = State.Text;
      this.sectionStart = this.index + 1;
    }
  }
  startEntity() {
    this.baseState = this.state;
    this.state = State.InEntity;
    this.entityStart = this.index;
    this.entityDecoder.startEntity(this.xmlMode ? DecodingMode.Strict : this.baseState === State.Text || this.baseState === State.InSpecialTag ? DecodingMode.Legacy : DecodingMode.Attribute);
  }
  stateInEntity() {
    const indexInBuffer = this.index - this.offset;
    const length = this.entityDecoder.write(this.buffer, indexInBuffer);
    if (length >= 0) {
      this.state = this.baseState;
      if (length === 0) {
        this.index -= 1;
      }
    } else {
      if (indexInBuffer < this.buffer.length && this.buffer.charCodeAt(indexInBuffer) === CharCodes2.Amp) {
        this.state = this.baseState;
        this.index -= 1;
        return;
      }
      this.index = this.offset + this.buffer.length - 1;
    }
  }
  cleanup() {
    if (this.running && this.sectionStart !== this.index) {
      if (this.state === State.Text || this.state === State.InPlainText || this.state === State.InSpecialTag && this.sequenceIndex === 0) {
        this.cbs.ontext(this.sectionStart, this.index);
        this.sectionStart = this.index;
      } else if (this.state === State.InAttributeValueDq || this.state === State.InAttributeValueSq || this.state === State.InAttributeValueNq) {
        this.cbs.onattribdata(this.sectionStart, this.index);
        this.sectionStart = this.index;
      }
    }
  }
  shouldContinue() {
    return this.index < this.buffer.length + this.offset && this.running;
  }
  parse() {
    while (this.shouldContinue()) {
      const c = this.buffer.charCodeAt(this.index - this.offset);
      switch (this.state) {
        case State.Text: {
          this.stateText(c);
          break;
        }
        case State.InPlainText: {
          this.index = this.buffer.length + this.offset - 1;
          break;
        }
        case State.SpecialStartSequence: {
          this.stateSpecialStartSequence(c);
          break;
        }
        case State.InSpecialTag: {
          this.stateInSpecialTag(c);
          break;
        }
        case State.CDATASequence: {
          this.stateCDATASequence(c);
          break;
        }
        case State.DeclarationSequence: {
          this.stateDeclarationSequence(c);
          break;
        }
        case State.InAttributeValueDq: {
          this.stateInAttributeValueDoubleQuotes(c);
          break;
        }
        case State.InAttributeName: {
          this.stateInAttributeName(c);
          break;
        }
        case State.InCommentLike: {
          this.stateInCommentLike(c);
          break;
        }
        case State.InSpecialComment: {
          this.stateInSpecialComment(c);
          break;
        }
        case State.BeforeAttributeName: {
          this.stateBeforeAttributeName(c);
          break;
        }
        case State.InTagName: {
          this.stateInTagName(c);
          break;
        }
        case State.InClosingTagName: {
          this.stateInClosingTagName(c);
          break;
        }
        case State.BeforeTagName: {
          this.stateBeforeTagName(c);
          break;
        }
        case State.AfterAttributeName: {
          this.stateAfterAttributeName(c);
          break;
        }
        case State.InAttributeValueSq: {
          this.stateInAttributeValueSingleQuotes(c);
          break;
        }
        case State.BeforeAttributeValue: {
          this.stateBeforeAttributeValue(c);
          break;
        }
        case State.BeforeClosingTagName: {
          this.stateBeforeClosingTagName(c);
          break;
        }
        case State.AfterClosingTagName: {
          this.stateAfterClosingTagName(c);
          break;
        }
        case State.InAttributeValueNq: {
          this.stateInAttributeValueNoQuotes(c);
          break;
        }
        case State.InSelfClosingTag: {
          this.stateInSelfClosingTag(c);
          break;
        }
        case State.InDeclaration: {
          this.stateInDeclaration(c);
          break;
        }
        case State.BeforeDeclaration: {
          this.stateBeforeDeclaration(c);
          break;
        }
        case State.BeforeComment: {
          this.stateBeforeComment(c);
          break;
        }
        case State.InProcessingInstruction: {
          this.stateInProcessingInstruction(c);
          break;
        }
        case State.InEntity: {
          this.stateInEntity();
          break;
        }
      }
      this.index++;
    }
    this.cleanup();
  }
  finish() {
    if (this.state === State.InEntity) {
      this.entityDecoder.end();
      this.state = this.baseState;
    }
    this.handleTrailingData();
    this.cbs.onend();
  }
  handleTrailingCommentLikeData(endIndex) {
    if (this.state !== State.InCommentLike) {
      return false;
    }
    if (this.currentSequence === Sequences.CdataEnd) {
      if (this.xmlMode) {
        if (this.sectionStart < endIndex) {
          this.cbs.oncdata(this.sectionStart, endIndex, 0);
        }
      } else {
        const cdataStart = this.sectionStart - Sequences.Cdata.length - 1;
        this.cbs.oncomment(cdataStart, endIndex, 0);
      }
    } else {
      const offset = this.xmlMode ? 0 : Math.min(this.sequenceIndex, Sequences.CommentEnd.length - 1);
      this.cbs.oncomment(this.sectionStart, endIndex, offset);
    }
    return true;
  }
  handleTrailingMarkupDeclaration(endIndex) {
    if (this.xmlMode) {
      switch (this.state) {
        case State.InSpecialComment:
        case State.BeforeComment:
        case State.CDATASequence:
        case State.DeclarationSequence:
        case State.InDeclaration: {
          this.cbs.ontext(this.sectionStart, endIndex);
          return true;
        }
        default: {
          return false;
        }
      }
    }
    switch (this.state) {
      case State.BeforeDeclaration:
      case State.InSpecialComment:
      case State.BeforeComment:
      case State.CDATASequence: {
        this.cbs.oncomment(this.sectionStart, endIndex, 0);
        return true;
      }
      case State.DeclarationSequence: {
        if (this.sequenceIndex !== Sequences.Doctype.length) {
          this.cbs.oncomment(this.sectionStart, endIndex, 0);
        }
        return true;
      }
      case State.InDeclaration: {
        return true;
      }
      default: {
        return false;
      }
    }
  }
  handleTrailingData() {
    const endIndex = this.buffer.length + this.offset;
    if (this.handleTrailingCommentLikeData(endIndex) || this.handleTrailingMarkupDeclaration(endIndex)) {
      return;
    }
    if (this.sectionStart >= endIndex) {
      return;
    }
    switch (this.state) {
      case State.InTagName:
      case State.BeforeAttributeName:
      case State.BeforeAttributeValue:
      case State.AfterAttributeName:
      case State.InAttributeName:
      case State.InAttributeValueSq:
      case State.InAttributeValueDq:
      case State.InAttributeValueNq:
      case State.InClosingTagName: {
        break;
      }
      default: {
        this.cbs.ontext(this.sectionStart, endIndex);
      }
    }
  }
  emitCodePoint(cp, consumed) {
    if (this.baseState !== State.Text && this.baseState !== State.InSpecialTag) {
      if (this.sectionStart < this.entityStart) {
        this.cbs.onattribdata(this.sectionStart, this.entityStart);
      }
      this.sectionStart = this.entityStart + consumed;
      this.index = this.sectionStart - 1;
      this.cbs.onattribentity(cp);
    } else {
      if (this.sectionStart < this.entityStart) {
        this.cbs.ontext(this.sectionStart, this.entityStart);
      }
      this.sectionStart = this.entityStart + consumed;
      this.index = this.sectionStart - 1;
      this.cbs.ontextentity(cp, this.sectionStart);
    }
  }
}

// ../imp-pinned/node_modules/htmlparser2/dist/Parser.js
var { fromCodePoint } = String;
var formTags = new Set([
  "input",
  "option",
  "optgroup",
  "select",
  "button",
  "datalist",
  "textarea"
]);
var pTag = new Set(["p"]);
var headingTags = new Set(["h1", "h2", "h3", "h4", "h5", "h6", "p"]);
var tableSectionTags = new Set(["thead", "tbody"]);
var ddtTags = new Set(["dd", "dt"]);
var rtpTags = new Set(["rt", "rp"]);
var openImpliesClose = new Map([
  ["tr", new Set(["tr", "th", "td"])],
  ["th", new Set(["th"])],
  ["td", new Set(["thead", "th", "td"])],
  ["body", new Set(["head", "link", "script"])],
  ["a", new Set(["a"])],
  ["li", new Set(["li"])],
  ["p", pTag],
  ["h1", headingTags],
  ["h2", headingTags],
  ["h3", headingTags],
  ["h4", headingTags],
  ["h5", headingTags],
  ["h6", headingTags],
  ["select", formTags],
  ["input", formTags],
  ["output", formTags],
  ["button", formTags],
  ["datalist", formTags],
  ["textarea", formTags],
  ["option", new Set(["option"])],
  ["optgroup", new Set(["optgroup", "option"])],
  ["dd", ddtTags],
  ["dt", ddtTags],
  ["address", pTag],
  ["article", pTag],
  ["aside", pTag],
  ["blockquote", pTag],
  ["details", pTag],
  ["div", pTag],
  ["dl", pTag],
  ["fieldset", pTag],
  ["figcaption", pTag],
  ["figure", pTag],
  ["footer", pTag],
  ["form", pTag],
  ["header", pTag],
  ["hr", pTag],
  ["main", pTag],
  ["nav", pTag],
  ["ol", pTag],
  ["pre", pTag],
  ["section", pTag],
  ["table", pTag],
  ["ul", pTag],
  ["rt", rtpTags],
  ["rp", rtpTags],
  ["tbody", tableSectionTags],
  ["tfoot", tableSectionTags]
]);
var DOCUMENT_TYPE = "doctype";
var voidElements = new Set([
  "area",
  "base",
  "basefont",
  "br",
  "col",
  "command",
  "embed",
  "frame",
  "hr",
  "img",
  "input",
  "isindex",
  "keygen",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr"
]);
var foreignContextElements = new Set(["math", "svg"]);
var htmlIntegrationElements = new Set([
  "mi",
  "mo",
  "mn",
  "ms",
  "mtext",
  "annotation-xml",
  "foreignObject",
  "desc",
  "title"
]);
var svgTagNameAdjustments = new Map([
  ["altglyph", "altGlyph"],
  ["altglyphdef", "altGlyphDef"],
  ["altglyphitem", "altGlyphItem"],
  ["animatecolor", "animateColor"],
  ["animatemotion", "animateMotion"],
  ["animatetransform", "animateTransform"],
  ["clippath", "clipPath"],
  ["feblend", "feBlend"],
  ["fecolormatrix", "feColorMatrix"],
  ["fecomponenttransfer", "feComponentTransfer"],
  ["fecomposite", "feComposite"],
  ["feconvolvematrix", "feConvolveMatrix"],
  ["fediffuselighting", "feDiffuseLighting"],
  ["fedisplacementmap", "feDisplacementMap"],
  ["fedistantlight", "feDistantLight"],
  ["fedropshadow", "feDropShadow"],
  ["feflood", "feFlood"],
  ["fefunca", "feFuncA"],
  ["fefuncb", "feFuncB"],
  ["fefuncg", "feFuncG"],
  ["fefuncr", "feFuncR"],
  ["fegaussianblur", "feGaussianBlur"],
  ["feimage", "feImage"],
  ["femerge", "feMerge"],
  ["femergenode", "feMergeNode"],
  ["femorphology", "feMorphology"],
  ["feoffset", "feOffset"],
  ["fepointlight", "fePointLight"],
  ["fespecularlighting", "feSpecularLighting"],
  ["fespotlight", "feSpotLight"],
  ["fetile", "feTile"],
  ["feturbulence", "feTurbulence"],
  ["foreignobject", "foreignObject"],
  ["glyphref", "glyphRef"],
  ["lineargradient", "linearGradient"],
  ["radialgradient", "radialGradient"],
  ["textpath", "textPath"]
]);
var ForeignContext;
(function(ForeignContext2) {
  ForeignContext2[ForeignContext2["None"] = 0] = "None";
  ForeignContext2[ForeignContext2["Svg"] = 1] = "Svg";
  ForeignContext2[ForeignContext2["MathML"] = 2] = "MathML";
})(ForeignContext || (ForeignContext = {}));
var reNameEnd = /\s|\//;

class Parser {
  options;
  startIndex = 0;
  endIndex = 0;
  openTagStart = 0;
  tagname = "";
  attribname = "";
  attribvalue = "";
  attribs = null;
  stack = [];
  foreignContext;
  cbs;
  lowerCaseTagNames;
  lowerCaseAttributeNames;
  recognizeSelfClosing;
  htmlMode;
  tokenizer;
  buffers = [];
  bufferOffset = 0;
  writeIndex = 0;
  ended = false;
  constructor(cbs, options = {}) {
    this.options = options;
    this.cbs = cbs ?? {};
    this.htmlMode = !this.options.xmlMode;
    this.lowerCaseTagNames = options.lowerCaseTags ?? this.htmlMode;
    this.lowerCaseAttributeNames = options.lowerCaseAttributeNames ?? this.htmlMode;
    this.recognizeSelfClosing = options.recognizeSelfClosing ?? !this.htmlMode;
    this.tokenizer = new (options.Tokenizer ?? Tokenizer)(this.options, this);
    this.foreignContext = [ForeignContext.None];
    this.cbs.onparserinit?.(this);
  }
  ontext(start, endIndex) {
    const data = this.getSlice(start, endIndex);
    this.endIndex = endIndex - 1;
    this.cbs.ontext?.(data);
    this.startIndex = endIndex;
  }
  ontextentity(cp, endIndex) {
    this.endIndex = endIndex - 1;
    this.cbs.ontext?.(fromCodePoint(cp));
    this.startIndex = endIndex;
  }
  isInForeignContext() {
    return this.foreignContext[0] !== ForeignContext.None;
  }
  isVoidElement(name) {
    return this.htmlMode && voidElements.has(name);
  }
  readTagName(start, endIndex) {
    const name = this.lowerCaseTagNames ? this.getSlice(start, endIndex).toLowerCase() : this.getSlice(start, endIndex);
    if (!(this.lowerCaseTagNames && this.htmlMode)) {
      return name;
    }
    if (this.foreignContext[0] === ForeignContext.Svg) {
      return svgTagNameAdjustments.get(name) ?? name;
    }
    if (this.foreignContext.length > 1) {
      const adjusted = svgTagNameAdjustments.get(name);
      if (adjusted !== undefined && this.stack.includes(adjusted)) {
        return adjusted;
      }
    }
    if (!this.isInForeignContext()) {
      return name === "image" ? "img" : name;
    }
    return name;
  }
  onopentagname(start, endIndex) {
    this.endIndex = endIndex;
    this.emitOpenTag(this.readTagName(start, endIndex));
  }
  emitOpenTag(name) {
    this.openTagStart = this.startIndex;
    this.tagname = name;
    if (this.htmlMode && name === "form" && this.stack.includes("form")) {
      this.tagname = "";
      return;
    }
    const impliesClose = this.htmlMode && openImpliesClose.get(name);
    if (impliesClose) {
      while (this.stack.length > 0 && impliesClose.has(this.stack[0])) {
        this.popElement(true);
      }
    }
    if (!this.isVoidElement(name)) {
      this.stack.unshift(name);
      if (this.htmlMode) {
        if (name === "svg") {
          this.foreignContext.unshift(ForeignContext.Svg);
        } else if (name === "math") {
          this.foreignContext.unshift(ForeignContext.MathML);
        } else if (htmlIntegrationElements.has(name)) {
          this.foreignContext.unshift(ForeignContext.None);
        }
      }
    }
    this.cbs.onopentagname?.(name);
    if (this.cbs.onopentag)
      this.attribs = {};
  }
  endOpenTag(isImplied) {
    this.startIndex = this.openTagStart;
    if (this.attribs) {
      this.cbs.onopentag?.(this.tagname, this.attribs, isImplied);
      this.attribs = null;
    }
    if (this.cbs.onclosetag && this.isVoidElement(this.tagname)) {
      this.cbs.onclosetag(this.tagname, true);
    }
    this.tagname = "";
  }
  onopentagend(endIndex) {
    this.endIndex = endIndex;
    this.endOpenTag(false);
    this.startIndex = endIndex + 1;
  }
  onclosetag(start, endIndex) {
    this.endIndex = endIndex;
    const name = this.readTagName(start, endIndex);
    if (!this.isVoidElement(name)) {
      const pos = this.stack.indexOf(name);
      if (pos !== -1) {
        for (let index = 0;index < pos; index++) {
          this.popElement(true);
        }
        this.popElement(false);
      } else if (this.htmlMode && name === "p") {
        this.emitOpenTag("p");
        this.closeCurrentTag(true);
      }
    } else if (this.htmlMode && name === "br") {
      this.cbs.onopentagname?.("br");
      this.cbs.onopentag?.("br", {}, true);
      this.cbs.onclosetag?.("br", false);
    }
    this.startIndex = endIndex + 1;
  }
  onselfclosingtag(endIndex) {
    this.endIndex = endIndex;
    if (this.recognizeSelfClosing || this.isInForeignContext()) {
      this.closeCurrentTag(false);
      this.startIndex = endIndex + 1;
    } else {
      this.onopentagend(endIndex);
    }
  }
  popElement(implied) {
    const element = this.stack.shift();
    if (this.htmlMode && (foreignContextElements.has(element) || htmlIntegrationElements.has(element))) {
      this.foreignContext.shift();
    }
    this.cbs.onclosetag?.(element, implied);
  }
  closeCurrentTag(isOpenImplied) {
    const name = this.tagname;
    this.endOpenTag(isOpenImplied);
    if (this.stack[0] === name) {
      this.popElement(!isOpenImplied);
    }
  }
  onattribname(start, endIndex) {
    this.startIndex = start;
    const name = this.getSlice(start, endIndex);
    this.attribname = this.lowerCaseAttributeNames ? name.toLowerCase() : name;
  }
  onattribdata(start, endIndex) {
    this.attribvalue += this.getSlice(start, endIndex);
  }
  onattribentity(cp) {
    this.attribvalue += fromCodePoint(cp);
  }
  onattribend(quote, endIndex) {
    this.endIndex = endIndex;
    this.cbs.onattribute?.(this.attribname, this.attribvalue, quote === QuoteType.Double ? '"' : quote === QuoteType.Single ? "'" : quote === QuoteType.NoValue ? undefined : null);
    if (this.attribs && !Object.hasOwn(this.attribs, this.attribname)) {
      this.attribs[this.attribname] = this.attribvalue;
    }
    this.attribvalue = "";
  }
  getInstructionName(value) {
    const index = value.search(reNameEnd);
    let name = index < 0 ? value : value.substr(0, index);
    if (this.lowerCaseTagNames) {
      name = name.toLowerCase();
    }
    return name;
  }
  ondeclaration(start, endIndex) {
    this.endIndex = endIndex;
    const value = this.getSlice(start, endIndex);
    if (this.cbs.onprocessinginstruction) {
      const name = this.htmlMode ? this.lowerCaseTagNames ? DOCUMENT_TYPE : value.slice(0, DOCUMENT_TYPE.length) : this.getInstructionName(value);
      this.cbs.onprocessinginstruction(`!${name}`, `!${value}`);
    }
    this.startIndex = endIndex + 1;
  }
  onprocessinginstruction(start, endIndex) {
    this.endIndex = endIndex;
    const value = this.getSlice(start, endIndex);
    if (this.cbs.onprocessinginstruction) {
      const name = this.getInstructionName(value);
      this.cbs.onprocessinginstruction(`?${name}`, `?${value}`);
    }
    this.startIndex = endIndex + 1;
  }
  oncomment(start, endIndex, offset) {
    this.endIndex = endIndex;
    this.cbs.oncomment?.(this.getSlice(start, endIndex - offset));
    this.cbs.oncommentend?.();
    this.startIndex = endIndex + 1;
  }
  oncdata(start, endIndex, offset) {
    this.endIndex = endIndex;
    const value = this.getSlice(start, endIndex - offset);
    if (!this.htmlMode || this.options.recognizeCDATA) {
      this.cbs.oncdatastart?.();
      this.cbs.ontext?.(value);
      this.cbs.oncdataend?.();
    } else if (this.isInForeignContext()) {
      this.cbs.ontext?.(value);
    } else {
      this.cbs.oncomment?.(`[CDATA[${value}]]`);
      this.cbs.oncommentend?.();
    }
    this.startIndex = endIndex + 1;
  }
  onend() {
    if (this.cbs.onclosetag) {
      this.endIndex = this.startIndex;
      for (let index = 0;index < this.stack.length; index++) {
        this.cbs.onclosetag(this.stack[index], true);
      }
    }
    this.cbs.onend?.();
  }
  reset() {
    this.cbs.onreset?.();
    this.tokenizer.reset();
    this.tagname = "";
    this.attribname = "";
    this.attribvalue = "";
    this.attribs = null;
    this.stack.length = 0;
    this.startIndex = 0;
    this.endIndex = 0;
    this.cbs.onparserinit?.(this);
    this.buffers.length = 0;
    this.foreignContext.length = 0;
    this.foreignContext.unshift(ForeignContext.None);
    this.bufferOffset = 0;
    this.writeIndex = 0;
    this.ended = false;
  }
  parseComplete(data) {
    this.reset();
    this.end(data);
  }
  getSlice(start, end) {
    if (start === end) {
      return "";
    }
    while (start - this.bufferOffset >= this.buffers[0].length) {
      this.shiftBuffer();
    }
    let slice = this.buffers[0].slice(start - this.bufferOffset, end - this.bufferOffset);
    while (end - this.bufferOffset > this.buffers[0].length) {
      this.shiftBuffer();
      slice += this.buffers[0].slice(0, end - this.bufferOffset);
    }
    return slice;
  }
  shiftBuffer() {
    this.bufferOffset += this.buffers[0].length;
    this.writeIndex--;
    this.buffers.shift();
  }
  write(chunk) {
    if (this.ended) {
      this.cbs.onerror?.(new Error(".write() after done!"));
      return;
    }
    this.buffers.push(chunk);
    if (this.tokenizer.running) {
      this.tokenizer.write(chunk);
      this.writeIndex++;
    }
  }
  end(chunk) {
    if (this.ended) {
      this.cbs.onerror?.(new Error(".end() after done!"));
      return;
    }
    if (chunk)
      this.write(chunk);
    this.ended = true;
    this.tokenizer.end();
  }
  pause() {
    this.tokenizer.pause();
  }
  resume() {
    this.tokenizer.resume();
    while (this.tokenizer.running && this.writeIndex < this.buffers.length) {
      this.tokenizer.write(this.buffers[this.writeIndex++]);
    }
    if (this.ended)
      this.tokenizer.end();
  }
}
// ../imp-pinned/node_modules/domelementtype/dist/index.js
var exports_dist = {};
__export(exports_dist, {
  isTag: () => isTag,
  Text: () => Text,
  Tag: () => Tag,
  Style: () => Style,
  Script: () => Script,
  Root: () => Root,
  ElementType: () => ElementType,
  Doctype: () => Doctype,
  Directive: () => Directive,
  Comment: () => Comment,
  CDATA: () => CDATA
});
var ElementType;
(function(ElementType2) {
  ElementType2["Root"] = "root";
  ElementType2["Text"] = "text";
  ElementType2["Directive"] = "directive";
  ElementType2["Comment"] = "comment";
  ElementType2["Script"] = "script";
  ElementType2["Style"] = "style";
  ElementType2["Tag"] = "tag";
  ElementType2["CDATA"] = "cdata";
  ElementType2["Doctype"] = "doctype";
})(ElementType || (ElementType = {}));
function isTag(element) {
  return element.type === ElementType.Tag || element.type === ElementType.Script || element.type === ElementType.Style;
}
var Root = ElementType.Root;
var Text = ElementType.Text;
var Directive = ElementType.Directive;
var Comment = ElementType.Comment;
var Script = ElementType.Script;
var Style = ElementType.Style;
var Tag = ElementType.Tag;
var CDATA = ElementType.CDATA;
var Doctype = ElementType.Doctype;

// ../imp-pinned/node_modules/domhandler/dist/node.js
class Node {
  parent = null;
  prev = null;
  next = null;
  startIndex = null;
  endIndex = null;
  get parentNode() {
    return this.parent;
  }
  set parentNode(parent) {
    this.parent = parent;
  }
  get previousSibling() {
    return this.prev;
  }
  set previousSibling(previous) {
    this.prev = previous;
  }
  get nextSibling() {
    return this.next;
  }
  set nextSibling(next) {
    this.next = next;
  }
  cloneNode(recursive = false) {
    return cloneNode(this, recursive);
  }
}

class DataNode extends Node {
  data;
  constructor(data) {
    super();
    this.data = data;
  }
  get nodeValue() {
    return this.data;
  }
  set nodeValue(data) {
    this.data = data;
  }
}

class Text2 extends DataNode {
  type = ElementType.Text;
  get nodeType() {
    return 3;
  }
}

class Comment2 extends DataNode {
  type = ElementType.Comment;
  get nodeType() {
    return 8;
  }
}

class ProcessingInstruction extends DataNode {
  type = ElementType.Directive;
  name;
  constructor(name, data) {
    super(data);
    this.name = name;
  }
  get nodeType() {
    return 1;
  }
  "x-name";
  "x-publicId";
  "x-systemId";
}

class NodeWithChildren extends Node {
  children;
  constructor(children) {
    super();
    this.children = children;
  }
  get firstChild() {
    return this.children[0] ?? null;
  }
  get lastChild() {
    return this.children.length > 0 ? this.children[this.children.length - 1] : null;
  }
  get childNodes() {
    return this.children;
  }
  set childNodes(children) {
    this.children = children;
  }
}

class CDATA2 extends NodeWithChildren {
  type = ElementType.CDATA;
  get nodeType() {
    return 4;
  }
}

class Document extends NodeWithChildren {
  type = ElementType.Root;
  get nodeType() {
    return 9;
  }
}

class Element extends NodeWithChildren {
  name;
  attribs;
  type;
  constructor(name, attribs, children = [], type = name === "script" ? ElementType.Script : name === "style" ? ElementType.Style : ElementType.Tag) {
    super(children);
    this.name = name;
    this.attribs = attribs;
    this.type = type;
  }
  get nodeType() {
    return 1;
  }
  get tagName() {
    return this.name;
  }
  set tagName(name) {
    this.name = name;
  }
  get attributes() {
    return Object.keys(this.attribs).map((name) => ({
      name,
      value: this.attribs[name],
      namespace: this["x-attribsNamespace"]?.[name],
      prefix: this["x-attribsPrefix"]?.[name]
    }));
  }
  namespace;
  "x-attribsNamespace";
  "x-attribsPrefix";
}
function isTag2(node) {
  return isTag(node);
}
function isCDATA(node) {
  return node.type === ElementType.CDATA;
}
function isText(node) {
  return node.type === ElementType.Text;
}
function isComment(node) {
  return node.type === ElementType.Comment;
}
function isDirective(node) {
  return node.type === ElementType.Directive;
}
function isDocument(node) {
  return node.type === ElementType.Root;
}
function hasChildren(node) {
  return Object.hasOwn(node, "children");
}
function cloneNode(node, recursive = false) {
  let result;
  if (isText(node)) {
    result = new Text2(node.data);
  } else if (isComment(node)) {
    result = new Comment2(node.data);
  } else if (isTag2(node)) {
    const children = recursive ? cloneChildren(node.children) : [];
    const clone = new Element(node.name, { ...node.attribs }, children);
    for (const child of children) {
      child.parent = clone;
    }
    if (node.namespace != null) {
      clone.namespace = node.namespace;
    }
    if (node["x-attribsNamespace"]) {
      clone["x-attribsNamespace"] = { ...node["x-attribsNamespace"] };
    }
    if (node["x-attribsPrefix"]) {
      clone["x-attribsPrefix"] = { ...node["x-attribsPrefix"] };
    }
    result = clone;
  } else if (isCDATA(node)) {
    const children = recursive ? cloneChildren(node.children) : [];
    const clone = new CDATA2(children);
    for (const child of children) {
      child.parent = clone;
    }
    result = clone;
  } else if (isDocument(node)) {
    const children = recursive ? cloneChildren(node.children) : [];
    const clone = new Document(children);
    for (const child of children) {
      child.parent = clone;
    }
    if (node["x-mode"]) {
      clone["x-mode"] = node["x-mode"];
    }
    result = clone;
  } else if (isDirective(node)) {
    const instruction = new ProcessingInstruction(node.name, node.data);
    if (node["x-name"] != null) {
      instruction["x-name"] = node["x-name"];
      instruction["x-publicId"] = node["x-publicId"];
      instruction["x-systemId"] = node["x-systemId"];
    }
    result = instruction;
  } else {
    throw new Error(`Not implemented yet: ${node.type}`);
  }
  result.startIndex = node.startIndex;
  result.endIndex = node.endIndex;
  if (node.sourceCodeLocation != null) {
    result.sourceCodeLocation = node.sourceCodeLocation;
  }
  return result;
}
function cloneChildren(childs) {
  const children = childs.map((child) => cloneNode(child, true));
  for (let index = 1;index < children.length; index++) {
    children[index].prev = children[index - 1];
    children[index - 1].next = children[index];
  }
  return children;
}

// ../imp-pinned/node_modules/domhandler/dist/index.js
var defaultOptions = {
  withStartIndices: false,
  withEndIndices: false,
  xmlMode: false
};

class DomHandler {
  dom = [];
  root = new Document(this.dom);
  callback;
  options;
  elementCB;
  done = false;
  tagStack = [this.root];
  lastNode = null;
  parser = null;
  constructor(callback, options, elementCB) {
    if (typeof options === "function") {
      elementCB = options;
      options = defaultOptions;
    }
    if (typeof callback === "object") {
      options = callback;
      callback = undefined;
    }
    this.callback = callback ?? null;
    this.options = options ?? defaultOptions;
    this.elementCB = elementCB ?? null;
  }
  onparserinit(parser) {
    this.parser = parser;
  }
  onreset() {
    this.dom = [];
    this.root = new Document(this.dom);
    this.done = false;
    this.tagStack = [this.root];
    this.lastNode = null;
    this.parser = null;
  }
  onend() {
    if (this.done)
      return;
    this.done = true;
    this.parser = null;
    this.handleCallback(null);
  }
  onerror(error) {
    this.handleCallback(error);
  }
  onclosetag() {
    this.lastNode = null;
    const element = this.tagStack.pop();
    if (this.options.withEndIndices && this.parser) {
      element.endIndex = this.parser.endIndex;
    }
    if (this.elementCB)
      this.elementCB(element);
  }
  onopentag(name, attribs) {
    const type = this.options.xmlMode ? ElementType.Tag : undefined;
    const element = new Element(name, attribs, undefined, type);
    this.addNode(element);
    this.tagStack.push(element);
  }
  ontext(data) {
    const { lastNode } = this;
    if (lastNode && lastNode.type === ElementType.Text) {
      lastNode.data += data;
      if (this.options.withEndIndices && this.parser) {
        lastNode.endIndex = this.parser.endIndex;
      }
    } else {
      const node2 = new Text2(data);
      this.addNode(node2);
      this.lastNode = node2;
    }
  }
  oncomment(data) {
    if (this.lastNode && this.lastNode.type === ElementType.Comment) {
      this.lastNode.data += data;
      return;
    }
    const node2 = new Comment2(data);
    this.addNode(node2);
    this.lastNode = node2;
  }
  oncommentend() {
    this.lastNode = null;
  }
  oncdatastart() {
    const text = new Text2("");
    const node2 = new CDATA2([text]);
    this.addNode(node2);
    text.parent = node2;
    this.lastNode = text;
  }
  oncdataend() {
    this.lastNode = null;
  }
  onprocessinginstruction(name, data) {
    const node2 = new ProcessingInstruction(name, data);
    this.addNode(node2);
  }
  handleCallback(error) {
    if (typeof this.callback === "function") {
      this.callback(error, this.dom);
    } else if (error) {
      throw error;
    }
  }
  addNode(node2) {
    const parent = this.tagStack[this.tagStack.length - 1];
    const previousSibling = parent.children[parent.children.length - 1];
    if (this.options.withStartIndices && this.parser) {
      node2.startIndex = this.parser.startIndex;
    }
    if (this.options.withEndIndices && this.parser) {
      node2.endIndex = this.parser.endIndex;
    }
    parent.children.push(node2);
    if (previousSibling) {
      node2.prev = previousSibling;
      previousSibling.next = node2;
    }
    node2.parent = parent;
    this.lastNode = null;
  }
}
// ../imp-pinned/node_modules/domutils/dist/index.js
var exports_dist2 = {};
__export(exports_dist2, {
  uniqueSort: () => uniqueSort,
  textContent: () => textContent,
  testElement: () => testElement,
  replaceElement: () => replaceElement,
  removeSubsets: () => removeSubsets,
  removeElement: () => removeElement,
  prevElementSibling: () => prevElementSibling,
  prependChild: () => prependChild,
  prepend: () => prepend,
  nextElementSibling: () => nextElementSibling,
  innerText: () => innerText,
  hasAttrib: () => hasAttrib,
  getText: () => getText,
  getSiblings: () => getSiblings,
  getParent: () => getParent,
  getOuterHTML: () => getOuterHTML,
  getName: () => getName,
  getInnerHTML: () => getInnerHTML,
  getFeed: () => getFeed,
  getElementsByTagType: () => getElementsByTagType,
  getElementsByTagName: () => getElementsByTagName,
  getElementsByClassName: () => getElementsByClassName,
  getElements: () => getElements,
  getElementById: () => getElementById,
  getChildren: () => getChildren,
  getAttributeValue: () => getAttributeValue,
  findOne: () => findOne,
  findAll: () => findAll,
  find: () => find,
  filter: () => filter,
  existsOne: () => existsOne,
  compareDocumentPosition: () => compareDocumentPosition,
  appendChild: () => appendChild,
  append: () => append,
  DocumentPosition: () => DocumentPosition
});

// ../imp-pinned/node_modules/domutils/dist/querying.js
function filter(test, node2, recurse = true, limit = Number.POSITIVE_INFINITY) {
  return find(test, Array.isArray(node2) ? node2 : [node2], recurse, limit);
}
function find(test, nodes, recurse, limit) {
  const result = [];
  const nodeStack = [Array.isArray(nodes) ? nodes : [nodes]];
  const indexStack = [0];
  for (;; ) {
    if (indexStack[0] >= nodeStack[0].length) {
      if (indexStack.length === 1) {
        return result;
      }
      nodeStack.shift();
      indexStack.shift();
      continue;
    }
    const element = nodeStack[0][indexStack[0]++];
    if (test(element)) {
      result.push(element);
      if (--limit <= 0)
        return result;
    }
    if (recurse && hasChildren(element) && element.children.length > 0) {
      indexStack.unshift(0);
      nodeStack.unshift(element.children);
    }
  }
}
function findOne(test, nodes, recurse = true) {
  const searchedNodes = Array.isArray(nodes) ? nodes : [nodes];
  for (const node2 of searchedNodes) {
    if (isTag2(node2) && test(node2)) {
      return node2;
    }
    if (recurse && hasChildren(node2) && node2.children.length > 0) {
      const found = findOne(test, node2.children, true);
      if (found)
        return found;
    }
  }
  return null;
}
function existsOne(test, nodes) {
  return (Array.isArray(nodes) ? nodes : [nodes]).some((node2) => isTag2(node2) && test(node2) || hasChildren(node2) && existsOne(test, node2.children));
}
function findAll(test, nodes) {
  const result = [];
  const nodeStack = [Array.isArray(nodes) ? nodes : [nodes]];
  const indexStack = [0];
  for (;; ) {
    if (indexStack[0] >= nodeStack[0].length) {
      if (nodeStack.length === 1) {
        return result;
      }
      nodeStack.shift();
      indexStack.shift();
      continue;
    }
    const element = nodeStack[0][indexStack[0]++];
    if (isTag2(element) && test(element))
      result.push(element);
    if (hasChildren(element) && element.children.length > 0) {
      indexStack.unshift(0);
      nodeStack.unshift(element.children);
    }
  }
}

// ../imp-pinned/node_modules/domutils/dist/legacy.js
var Checks = {
  tag_name(name) {
    if (typeof name === "function") {
      return (element) => isTag2(element) && name(element.name);
    }
    if (name === "*") {
      return isTag2;
    }
    return (element) => isTag2(element) && element.name === name;
  },
  tag_type(type) {
    if (typeof type === "function") {
      return (element) => type(element.type);
    }
    return (element) => element.type === type;
  },
  tag_contains(data) {
    if (typeof data === "function") {
      return (element) => isText(element) && data(element.data);
    }
    return (element) => isText(element) && element.data === data;
  }
};
function getAttribCheck(attrib, value) {
  if (typeof value === "function") {
    return (element) => isTag2(element) && value(element.attribs[attrib]);
  }
  return (element) => isTag2(element) && element.attribs[attrib] === value;
}
function combineFuncs(a, b) {
  return (element) => a(element) || b(element);
}
function compileTest(options) {
  const funcs = Object.keys(options).map((key) => {
    const value = options[key];
    return Object.hasOwn(Checks, key) ? Checks[key](value) : getAttribCheck(key, value);
  });
  return funcs.length === 0 ? null : funcs.reduce(combineFuncs);
}
function testElement(options, node2) {
  const test = compileTest(options);
  return test ? test(node2) : true;
}
function getElements(options, nodes, recurse, limit = Number.POSITIVE_INFINITY) {
  const test = compileTest(options);
  return test ? filter(test, nodes, recurse, limit) : [];
}
function getElementById(id, nodes, recurse = true) {
  if (!Array.isArray(nodes))
    nodes = [nodes];
  return findOne(getAttribCheck("id", id), nodes, recurse);
}
function getElementsByTagName(tagName, nodes, recurse = true, limit = Number.POSITIVE_INFINITY) {
  return filter(Checks["tag_name"](tagName), nodes, recurse, limit);
}
function getElementsByClassName(className, nodes, recurse = true, limit = Number.POSITIVE_INFINITY) {
  return filter(getAttribCheck("class", className), nodes, recurse, limit);
}
function getElementsByTagType(type, nodes, recurse = true, limit = Number.POSITIVE_INFINITY) {
  return filter(Checks["tag_type"](type), nodes, recurse, limit);
}

// ../imp-pinned/node_modules/entities/dist/escape.js
var xmlCodeMap = new Map([
  [34, "&quot;"],
  [38, "&amp;"],
  [39, "&apos;"],
  [60, "&lt;"],
  [62, "&gt;"]
]);
var getCodePoint = typeof String.prototype.codePointAt === "function" ? (input, index) => input.codePointAt(index) : (c, index) => (c.charCodeAt(index) & 64512) === 55296 ? (c.charCodeAt(index) - 55296) * 1024 + c.charCodeAt(index + 1) - 56320 + 65536 : c.charCodeAt(index);
var XML_BITSET_VALUE = 1342177476;
function encodeXML(input) {
  let out;
  let last = 0;
  const { length } = input;
  for (let index = 0;index < length; index++) {
    const char = input.charCodeAt(index);
    if (char < 128 && ((XML_BITSET_VALUE >>> char & 1) === 0 || char >= 64 || char < 32)) {
      continue;
    }
    if (out === undefined)
      out = input.substring(0, index);
    else if (last !== index)
      out += input.substring(last, index);
    if (char < 64) {
      out += xmlCodeMap.get(char);
      last = index + 1;
      continue;
    }
    const cp = getCodePoint(input, index);
    out += `&#x${cp.toString(16)};`;
    if (cp !== char)
      index++;
    last = index + 1;
  }
  if (out === undefined)
    return input;
  if (last < length)
    out += input.substr(last);
  return out;
}
function getEscaper(regex, map) {
  return function escape(data) {
    let match;
    let lastIndex = 0;
    let result = "";
    while (match = regex.exec(data)) {
      if (lastIndex !== match.index) {
        result += data.substring(lastIndex, match.index);
      }
      result += map.get(match[0].charCodeAt(0));
      lastIndex = match.index + 1;
    }
    return result + data.substring(lastIndex);
  };
}
var escapeAttribute = /* @__PURE__ */ getEscaper(/["&\u00A0]/g, new Map([
  [34, "&quot;"],
  [38, "&amp;"],
  [160, "&nbsp;"]
]));
var escapeText = /* @__PURE__ */ getEscaper(/[&<>\u00A0]/g, new Map([
  [38, "&amp;"],
  [60, "&lt;"],
  [62, "&gt;"],
  [160, "&nbsp;"]
]));

// ../imp-pinned/node_modules/entities/dist/index.js
var EntityLevel;
(function(EntityLevel2) {
  EntityLevel2[EntityLevel2["XML"] = 0] = "XML";
  EntityLevel2[EntityLevel2["HTML"] = 1] = "HTML";
})(EntityLevel || (EntityLevel = {}));
var EncodingMode;
(function(EncodingMode2) {
  EncodingMode2[EncodingMode2["UTF8"] = 0] = "UTF8";
  EncodingMode2[EncodingMode2["ASCII"] = 1] = "ASCII";
  EncodingMode2[EncodingMode2["Extensive"] = 2] = "Extensive";
  EncodingMode2[EncodingMode2["Attribute"] = 3] = "Attribute";
  EncodingMode2[EncodingMode2["Text"] = 4] = "Text";
})(EncodingMode || (EncodingMode = {}));

// ../imp-pinned/node_modules/dom-serializer/dist/foreign-names.js
var elementNames = new Map("altGlyph altGlyphDef altGlyphItem animateColor animateMotion animateTransform clipPath feBlend feColorMatrix feComponentTransfer feComposite feConvolveMatrix feDiffuseLighting feDisplacementMap feDistantLight feDropShadow feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feImage feMerge feMergeNode feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence foreignObject glyphRef linearGradient radialGradient textPath".split(" ").map((name) => [name.toLowerCase(), name]));
var attributeNames = new Map("definitionURL attributeName attributeType baseFrequency baseProfile calcMode clipPathUnits diffuseConstant edgeMode filterUnits glyphRef gradientTransform gradientUnits kernelMatrix kernelUnitLength keyPoints keySplines keyTimes lengthAdjust limitingConeAngle markerHeight markerUnits markerWidth maskContentUnits maskUnits numOctaves pathLength patternContentUnits patternTransform patternUnits pointsAtX pointsAtY pointsAtZ preserveAlpha preserveAspectRatio primitiveUnits refX refY repeatCount repeatDur requiredExtensions requiredFeatures specularConstant specularExponent spreadMethod startOffset stdDeviation stitchTiles surfaceScale systemLanguage tableValues targetX targetY textLength viewBox viewTarget xChannelSelector yChannelSelector zoomAndPan".split(" ").map((name) => [name.toLowerCase(), name]));

// ../imp-pinned/node_modules/dom-serializer/dist/index.js
var unencodedElements = new Set("style script xmp iframe noembed noframes plaintext noscript".split(" "));
var voidElements2 = new Set("area base basefont br col command embed frame hr img input isindex keygen link meta param source track wbr".split(" "));
var foreignElements = new Set(["svg", "math"]);
var foreignModeIntegrationPoints = new Set("mi mo mn ms mtext annotation-xml foreignObject desc title".split(" "));
function render(node2, options = {}) {
  const nodes = "length" in node2 ? node2 : [node2];
  const xmlMode = options.xmlMode ?? false;
  let output = "";
  for (let index = 0;index < nodes.length; index++) {
    output += renderNode(nodes[index], options, xmlMode);
  }
  return output;
}
var dist_default = render;
function renderChildren(children, options, xmlMode) {
  let output = "";
  for (let index = 0;index < children.length; index++) {
    output += renderNode(children[index], options, xmlMode);
  }
  return output;
}
function renderNode(node2, options, xmlMode) {
  switch (node2.type) {
    case Root: {
      return renderChildren(node2.children, options, xmlMode);
    }
    case Directive: {
      return `<${node2.data}>`;
    }
    case Comment: {
      return `<!--${node2.data}-->`;
    }
    case CDATA: {
      return `<![CDATA[${node2.children[0].data}]]>`;
    }
    case Script:
    case Style:
    case Tag: {
      return renderTag(node2, options, xmlMode);
    }
    case Text: {
      const element = node2;
      const data = element.data || "";
      if ((options.encodeEntities ?? options.decodeEntities) !== false && !(!xmlMode && element.parent && unencodedElements.has(element.parent.name))) {
        return xmlMode || options.encodeEntities !== "utf8" ? encodeXML(data) : escapeText(data);
      }
      return data;
    }
  }
}
function renderTag(element, options, xmlMode) {
  if (xmlMode === "foreign") {
    element.name = elementNames.get(element.name) ?? element.name;
    if (element.parent && foreignModeIntegrationPoints.has(element.parent.name)) {
      xmlMode = false;
    }
  }
  if (!xmlMode && foreignElements.has(element.name)) {
    xmlMode = "foreign";
  }
  const { name, children } = element;
  const isVoid = !xmlMode && voidElements2.has(name);
  let tag = `<${name}${formatAttributes(element.attribs, options, xmlMode)}`;
  if (children.length === 0 && (xmlMode ? options.selfClosingTags !== false : options.selfClosingTags && isVoid)) {
    tag += xmlMode ? "/>" : " />";
  } else {
    tag += ">";
    if (children.length > 0) {
      tag += renderChildren(children, options, xmlMode);
    }
    if (!isVoid) {
      tag += `</${name}>`;
    }
  }
  return tag;
}
function replaceQuotes(value) {
  return value.replaceAll('"', "&quot;");
}
function formatAttributes(attributes, options, xmlMode) {
  if (!attributes)
    return "";
  const encode = (options.encodeEntities ?? options.decodeEntities) === false ? replaceQuotes : xmlMode || options.encodeEntities !== "utf8" ? encodeXML : escapeAttribute;
  const isForeign = xmlMode === "foreign";
  const showEmpty = !!(options.emptyAttrs ?? xmlMode);
  let result = "";
  for (const key in attributes) {
    if (!Object.hasOwn(attributes, key))
      continue;
    const value = attributes[key];
    const k = isForeign ? attributeNames.get(key) ?? key : key;
    result += !showEmpty && (value == null || value === "") ? ` ${k}` : ` ${k}="${encode(value == null ? "" : String(value))}"`;
  }
  return result;
}

// ../imp-pinned/node_modules/domutils/dist/stringify.js
function getOuterHTML(node2, options) {
  return dist_default(node2, options);
}
function getInnerHTML(node2, options) {
  return hasChildren(node2) ? node2.children.map((node3) => getOuterHTML(node3, options)).join("") : "";
}
function getText(node2) {
  if (Array.isArray(node2))
    return node2.map(getText).join("");
  if (isTag2(node2))
    return node2.name === "br" ? `
` : getText(node2.children);
  if (isCDATA(node2))
    return getText(node2.children);
  if (isText(node2))
    return node2.data;
  return "";
}
function textContent(node2) {
  if (Array.isArray(node2))
    return node2.map(textContent).join("");
  if (hasChildren(node2) && !isComment(node2)) {
    return textContent(node2.children);
  }
  if (isText(node2))
    return node2.data;
  return "";
}
function innerText(node2) {
  if (Array.isArray(node2))
    return node2.map(innerText).join("");
  if (hasChildren(node2) && (node2.type === ElementType.Tag || isCDATA(node2))) {
    return innerText(node2.children);
  }
  if (isText(node2))
    return node2.data;
  return "";
}

// ../imp-pinned/node_modules/domutils/dist/feeds.js
function getFeed(document) {
  const feedRoot = getOneElement(isValidFeed, document);
  return feedRoot ? feedRoot.name === "feed" ? getAtomFeed(feedRoot) : getRssFeed(feedRoot) : null;
}
function getAtomFeed(feedRoot) {
  const childs = feedRoot.children;
  const feed = {
    type: "atom",
    items: getElementsByTagName("entry", childs).map((item) => {
      const { children } = item;
      const entry = { media: getMediaElements(children) };
      addConditionally(entry, "id", "id", children);
      addConditionally(entry, "title", "title", children);
      const href2 = getOneElement("link", children)?.attribs["href"];
      if (href2) {
        entry.link = href2;
      }
      const description = fetch("summary", children) || fetch("content", children);
      if (description) {
        entry.description = description;
      }
      const pubDate = fetch("updated", children);
      if (pubDate) {
        entry.pubDate = new Date(pubDate);
      }
      return entry;
    })
  };
  addConditionally(feed, "id", "id", childs);
  addConditionally(feed, "title", "title", childs);
  const href = getOneElement("link", childs)?.attribs["href"];
  if (href) {
    feed.link = href;
  }
  addConditionally(feed, "description", "subtitle", childs);
  const updated = fetch("updated", childs);
  if (updated) {
    feed.updated = new Date(updated);
  }
  addConditionally(feed, "author", "email", childs, true);
  return feed;
}
function getRssFeed(feedRoot) {
  const childs = getOneElement("channel", feedRoot.children)?.children ?? [];
  const feed = {
    type: feedRoot.name.substr(0, 3),
    id: "",
    items: getElementsByTagName("item", feedRoot.children).map((item) => {
      const { children } = item;
      const entry = { media: getMediaElements(children) };
      addConditionally(entry, "id", "guid", children);
      addConditionally(entry, "title", "title", children);
      addConditionally(entry, "link", "link", children);
      addConditionally(entry, "description", "description", children);
      const pubDate = fetch("pubDate", children) || fetch("dc:date", children);
      if (pubDate)
        entry.pubDate = new Date(pubDate);
      return entry;
    })
  };
  addConditionally(feed, "title", "title", childs);
  addConditionally(feed, "link", "link", childs);
  addConditionally(feed, "description", "description", childs);
  const updated = fetch("lastBuildDate", childs);
  if (updated) {
    feed.updated = new Date(updated);
  }
  addConditionally(feed, "author", "managingEditor", childs, true);
  return feed;
}
var MEDIA_KEYS_STRING = ["url", "type", "lang"];
var MEDIA_KEYS_INT = [
  "fileSize",
  "bitrate",
  "framerate",
  "samplingrate",
  "channels",
  "duration",
  "height",
  "width"
];
function getMediaElements(where) {
  return getElementsByTagName("media:content", where).map((element) => {
    const { attribs } = element;
    const media = {
      medium: attribs["medium"],
      isDefault: !!attribs["isDefault"]
    };
    for (const attrib of MEDIA_KEYS_STRING) {
      if (attribs[attrib]) {
        media[attrib] = attribs[attrib];
      }
    }
    for (const attrib of MEDIA_KEYS_INT) {
      if (attribs[attrib]) {
        media[attrib] = Number.parseInt(attribs[attrib], 10);
      }
    }
    if (attribs["expression"]) {
      media.expression = attribs["expression"];
    }
    return media;
  });
}
function getOneElement(tagName, node2) {
  return getElementsByTagName(tagName, node2, true, 1)[0];
}
function fetch(tagName, where, recurse = false) {
  return textContent(getElementsByTagName(tagName, where, recurse, 1)).trim();
}
function addConditionally(object, property, tagName, where, recurse = false) {
  const value = fetch(tagName, where, recurse);
  if (value)
    object[property] = value;
}
function isValidFeed(value) {
  return value === "rss" || value === "feed" || value === "rdf:RDF";
}
// ../imp-pinned/node_modules/domutils/dist/helpers.js
function removeSubsets(nodes) {
  let index = nodes.length;
  while (--index >= 0) {
    const node2 = nodes[index];
    if (index > 0 && nodes.lastIndexOf(node2, index - 1) >= 0) {
      nodes.splice(index, 1);
      continue;
    }
    for (let ancestor = node2.parent;ancestor; ancestor = ancestor.parent) {
      if (nodes.includes(ancestor)) {
        nodes.splice(index, 1);
        break;
      }
    }
  }
  return nodes;
}
var DocumentPosition;
(function(DocumentPosition2) {
  DocumentPosition2[DocumentPosition2["DISCONNECTED"] = 1] = "DISCONNECTED";
  DocumentPosition2[DocumentPosition2["PRECEDING"] = 2] = "PRECEDING";
  DocumentPosition2[DocumentPosition2["FOLLOWING"] = 4] = "FOLLOWING";
  DocumentPosition2[DocumentPosition2["CONTAINS"] = 8] = "CONTAINS";
  DocumentPosition2[DocumentPosition2["CONTAINED_BY"] = 16] = "CONTAINED_BY";
})(DocumentPosition || (DocumentPosition = {}));
function compareDocumentPosition(nodeA, nodeB) {
  const aParents = [];
  const bParents = [];
  if (nodeA === nodeB) {
    return 0;
  }
  let current = hasChildren(nodeA) ? nodeA : nodeA.parent;
  while (current) {
    aParents.unshift(current);
    current = current.parent;
  }
  current = hasChildren(nodeB) ? nodeB : nodeB.parent;
  while (current) {
    bParents.unshift(current);
    current = current.parent;
  }
  const maxIndex = Math.min(aParents.length, bParents.length);
  let index = 0;
  while (index < maxIndex && aParents[index] === bParents[index]) {
    index++;
  }
  if (index === 0) {
    return DocumentPosition.DISCONNECTED;
  }
  const sharedParent = aParents[index - 1];
  const siblings = sharedParent.children;
  const aSibling = aParents[index];
  const bSibling = bParents[index];
  if (siblings.indexOf(aSibling) > siblings.indexOf(bSibling)) {
    if (sharedParent === nodeB) {
      return DocumentPosition.FOLLOWING | DocumentPosition.CONTAINED_BY;
    }
    return DocumentPosition.FOLLOWING;
  }
  if (sharedParent === nodeA) {
    return DocumentPosition.PRECEDING | DocumentPosition.CONTAINS;
  }
  return DocumentPosition.PRECEDING;
}
function uniqueSort(nodes) {
  nodes = nodes.filter((node2, index, array) => !array.includes(node2, index + 1));
  nodes.sort((a, b) => {
    const relative = compareDocumentPosition(a, b);
    if (relative & DocumentPosition.PRECEDING) {
      return -1;
    }
    if (relative & DocumentPosition.FOLLOWING) {
      return 1;
    }
    return 0;
  });
  return nodes;
}
// ../imp-pinned/node_modules/domutils/dist/manipulation.js
function removeElement(element) {
  if (element.prev)
    element.prev.next = element.next;
  if (element.next)
    element.next.prev = element.prev;
  if (element.parent) {
    const childs = element.parent.children;
    const childsIndex = childs.lastIndexOf(element);
    if (childsIndex !== -1) {
      childs.splice(childsIndex, 1);
    }
  }
  element.next = null;
  element.prev = null;
  element.parent = null;
}
function replaceElement(element, replacement) {
  replacement.prev = element.prev;
  if (replacement.prev) {
    replacement.prev.next = replacement;
  }
  replacement.next = element.next;
  if (replacement.next) {
    replacement.next.prev = replacement;
  }
  replacement.parent = element.parent;
  if (replacement.parent) {
    const { children } = replacement.parent;
    const elementIndex = children.lastIndexOf(element);
    if (elementIndex === -1) {
      return;
    }
    children[elementIndex] = replacement;
    element.parent = null;
  }
}
function appendChild(parent, child) {
  removeElement(child);
  child.next = null;
  child.parent = parent;
  if (parent.children.push(child) > 1) {
    const sibling = parent.children[parent.children.length - 2];
    sibling.next = child;
    child.prev = sibling;
  } else {
    child.prev = null;
  }
}
function append(element, next) {
  removeElement(next);
  const { parent } = element;
  const currentNext = element.next;
  next.next = currentNext;
  next.prev = element;
  element.next = next;
  next.parent = parent;
  if (currentNext) {
    currentNext.prev = next;
    if (parent) {
      const childs = parent.children;
      childs.splice(childs.lastIndexOf(currentNext), 0, next);
    }
  } else if (parent) {
    parent.children.push(next);
  }
}
function prependChild(parent, child) {
  removeElement(child);
  child.parent = parent;
  child.prev = null;
  if (parent.children.unshift(child) === 1) {
    child.next = null;
  } else {
    const sibling = parent.children[1];
    sibling.prev = child;
    child.next = sibling;
  }
}
function prepend(element, previous) {
  removeElement(previous);
  const { parent } = element;
  if (parent) {
    const childs = parent.children;
    childs.splice(childs.indexOf(element), 0, previous);
  }
  if (element.prev) {
    element.prev.next = previous;
  }
  previous.parent = parent;
  previous.prev = element.prev;
  previous.next = element;
  element.prev = previous;
}
// ../imp-pinned/node_modules/domutils/dist/traversal.js
function getChildren(element) {
  return hasChildren(element) ? element.children : [];
}
function getParent(element) {
  return element.parent || null;
}
function getSiblings(element) {
  const parent = getParent(element);
  if (parent != null)
    return getChildren(parent);
  const siblings = [element];
  let { prev, next } = element;
  while (prev != null) {
    siblings.unshift(prev);
    ({ prev } = prev);
  }
  while (next != null) {
    siblings.push(next);
    ({ next } = next);
  }
  return siblings;
}
function getAttributeValue(element, name) {
  const { attribs } = element;
  return attribs?.[name];
}
function hasAttrib(element, name) {
  const { attribs } = element;
  return attribs != null && Object.hasOwn(attribs, name) && attribs[name] != null;
}
function getName(element) {
  return element.name;
}
function nextElementSibling(element) {
  let { next } = element;
  while (next !== null && !isTag2(next))
    ({ next } = next);
  return next;
}
function prevElementSibling(element) {
  let { prev } = element;
  while (prev !== null && !isTag2(prev))
    ({ prev } = prev);
  return prev;
}
// ../imp-pinned/node_modules/htmlparser2/dist/index.js
function parseDocument(data, options) {
  const handler = new DomHandler(undefined, options);
  new Parser(handler, options).end(data);
  return handler.root;
}
function createDocumentStream(callback, options, elementCallback) {
  const handler = new DomHandler((error) => callback(error, handler.root), options, elementCallback);
  return new Parser(handler, options);
}
var parseFeedDefaultOptions = { xmlMode: true };
function parseFeed(feed, options = parseFeedDefaultOptions) {
  return getFeed(parseDocument(feed, options).children);
}
// ../imp-pinned/node_modules/css-select/dist/index.js
var exports_dist5 = {};
__export(exports_dist5, {
  selectOne: () => selectOne,
  selectAll: () => selectAll,
  prepareContext: () => prepareContext,
  is: () => is2,
  default: () => dist_default2,
  compile: () => compile2,
  _compileUnsafe: () => _compileUnsafe
});

// ../imp-pinned/node_modules/boolbase/dist/index.js
function trueFunc() {
  return true;
}
function falseFunc() {
  return false;
}

// ../imp-pinned/node_modules/css-what/dist/types.js
var SelectorType;
(function(SelectorType2) {
  SelectorType2["Attribute"] = "attribute";
  SelectorType2["Pseudo"] = "pseudo";
  SelectorType2["PseudoElement"] = "pseudo-element";
  SelectorType2["Tag"] = "tag";
  SelectorType2["Universal"] = "universal";
  SelectorType2["Adjacent"] = "adjacent";
  SelectorType2["Child"] = "child";
  SelectorType2["Descendant"] = "descendant";
  SelectorType2["Parent"] = "parent";
  SelectorType2["Sibling"] = "sibling";
  SelectorType2["ColumnCombinator"] = "column-combinator";
})(SelectorType || (SelectorType = {}));
var AttributeAction;
(function(AttributeAction2) {
  AttributeAction2["Any"] = "any";
  AttributeAction2["Element"] = "element";
  AttributeAction2["End"] = "end";
  AttributeAction2["Equals"] = "equals";
  AttributeAction2["Exists"] = "exists";
  AttributeAction2["Hyphen"] = "hyphen";
  AttributeAction2["Not"] = "not";
  AttributeAction2["Start"] = "start";
})(AttributeAction || (AttributeAction = {}));

// ../imp-pinned/node_modules/css-what/dist/parse.js
var reName = /^[^#\\]?(?:\\(?:[\da-f]{1,6}\s?|.)|[\w\u00B0-\uFFFF-])+/;
var reEscape = /\\([\da-f]{1,6}\s?|(\s)|.)/gi;
var CharCode;
(function(CharCode2) {
  CharCode2[CharCode2["LeftParenthesis"] = 40] = "LeftParenthesis";
  CharCode2[CharCode2["RightParenthesis"] = 41] = "RightParenthesis";
  CharCode2[CharCode2["LeftSquareBracket"] = 91] = "LeftSquareBracket";
  CharCode2[CharCode2["RightSquareBracket"] = 93] = "RightSquareBracket";
  CharCode2[CharCode2["Comma"] = 44] = "Comma";
  CharCode2[CharCode2["Period"] = 46] = "Period";
  CharCode2[CharCode2["Colon"] = 58] = "Colon";
  CharCode2[CharCode2["SingleQuote"] = 39] = "SingleQuote";
  CharCode2[CharCode2["DoubleQuote"] = 34] = "DoubleQuote";
  CharCode2[CharCode2["Plus"] = 43] = "Plus";
  CharCode2[CharCode2["Tilde"] = 126] = "Tilde";
  CharCode2[CharCode2["QuestionMark"] = 63] = "QuestionMark";
  CharCode2[CharCode2["ExclamationMark"] = 33] = "ExclamationMark";
  CharCode2[CharCode2["Slash"] = 47] = "Slash";
  CharCode2[CharCode2["Equal"] = 61] = "Equal";
  CharCode2[CharCode2["Dollar"] = 36] = "Dollar";
  CharCode2[CharCode2["Pipe"] = 124] = "Pipe";
  CharCode2[CharCode2["Circumflex"] = 94] = "Circumflex";
  CharCode2[CharCode2["Asterisk"] = 42] = "Asterisk";
  CharCode2[CharCode2["GreaterThan"] = 62] = "GreaterThan";
  CharCode2[CharCode2["LessThan"] = 60] = "LessThan";
  CharCode2[CharCode2["Hash"] = 35] = "Hash";
  CharCode2[CharCode2["LowerI"] = 105] = "LowerI";
  CharCode2[CharCode2["LowerS"] = 115] = "LowerS";
  CharCode2[CharCode2["BackSlash"] = 92] = "BackSlash";
  CharCode2[CharCode2["Space"] = 32] = "Space";
  CharCode2[CharCode2["Tab"] = 9] = "Tab";
  CharCode2[CharCode2["NewLine"] = 10] = "NewLine";
  CharCode2[CharCode2["FormFeed"] = 12] = "FormFeed";
  CharCode2[CharCode2["CarriageReturn"] = 13] = "CarriageReturn";
})(CharCode || (CharCode = {}));
var actionTypes = new Map([
  [CharCode.Tilde, AttributeAction.Element],
  [CharCode.Circumflex, AttributeAction.Start],
  [CharCode.Dollar, AttributeAction.End],
  [CharCode.Asterisk, AttributeAction.Any],
  [CharCode.ExclamationMark, AttributeAction.Not],
  [CharCode.Pipe, AttributeAction.Hyphen]
]);
var unpackPseudos = new Set([
  "has",
  "not",
  "matches",
  "is",
  "where",
  "host",
  "host-context"
]);
var pseudosToPseudoElements = new Set([
  "before",
  "after",
  "first-line",
  "first-letter"
]);
function isTraversal(selector) {
  switch (selector.type) {
    case SelectorType.Adjacent:
    case SelectorType.Child:
    case SelectorType.Descendant:
    case SelectorType.Parent:
    case SelectorType.Sibling:
    case SelectorType.ColumnCombinator: {
      return true;
    }
    case SelectorType.Attribute:
    case SelectorType.Pseudo:
    case SelectorType.PseudoElement:
    case SelectorType.Tag:
    case SelectorType.Universal: {
      return false;
    }
  }
}
var stripQuotesFromPseudos = new Set(["contains", "icontains"]);
function funescape(_, escaped, escapedWhitespace) {
  const high = Number.parseInt(escaped, 16) - 65536;
  return Number.isNaN(high) || escapedWhitespace ? escaped : high < 0 ? String.fromCharCode(high + 65536) : String.fromCharCode(high >> 10 | 55296, high & 1023 | 56320);
}
function unescapeCSS(cssString) {
  return cssString.replace(reEscape, funescape);
}
function isQuote(c) {
  return c === CharCode.SingleQuote || c === CharCode.DoubleQuote;
}
function isWhitespace2(c) {
  return c === CharCode.Space || c === CharCode.Tab || c === CharCode.NewLine || c === CharCode.FormFeed || c === CharCode.CarriageReturn;
}
function parse(selector) {
  const subselects = [];
  const endIndex = parseSelector(subselects, `${selector}`, 0);
  if (endIndex < selector.length) {
    throw new Error(`Unmatched selector: ${selector.slice(endIndex)}`);
  }
  return subselects;
}
function parseSelector(subselects, selector, selectorIndex) {
  let tokens = [];
  function getName2(offset) {
    const match = selector.slice(selectorIndex + offset).match(reName);
    if (!match) {
      throw new Error(`Expected name, found ${selector.slice(selectorIndex)}`);
    }
    const [name] = match;
    selectorIndex += offset + name.length;
    return unescapeCSS(name);
  }
  function stripWhitespace(offset) {
    selectorIndex += offset;
    while (selectorIndex < selector.length && isWhitespace2(selector.charCodeAt(selectorIndex))) {
      selectorIndex++;
    }
  }
  function readValueWithParenthesis() {
    selectorIndex += 1;
    const start = selectorIndex;
    for (let counter = 1;selectorIndex < selector.length; selectorIndex++) {
      switch (selector.charCodeAt(selectorIndex)) {
        case CharCode.BackSlash: {
          selectorIndex += 1;
          break;
        }
        case CharCode.LeftParenthesis: {
          counter += 1;
          break;
        }
        case CharCode.RightParenthesis: {
          counter -= 1;
          if (counter === 0) {
            return unescapeCSS(selector.slice(start, selectorIndex++));
          }
          break;
        }
      }
    }
    throw new Error("Parenthesis not matched");
  }
  function ensureNotTraversal() {
    if (tokens.length > 0 && isTraversal(tokens[tokens.length - 1])) {
      throw new Error("Did not expect successive traversals.");
    }
  }
  function addTraversal(type) {
    if (tokens.length > 0 && tokens[tokens.length - 1].type === SelectorType.Descendant) {
      tokens[tokens.length - 1].type = type;
      return;
    }
    ensureNotTraversal();
    tokens.push({ type });
  }
  function addSpecialAttribute(name, action) {
    tokens.push({
      type: SelectorType.Attribute,
      name,
      action,
      value: getName2(1),
      namespace: null,
      ignoreCase: "quirks"
    });
  }
  function finalizeSubselector() {
    if (tokens.length > 0 && tokens[tokens.length - 1].type === SelectorType.Descendant) {
      tokens.pop();
    }
    if (tokens.length === 0) {
      throw new Error("Empty sub-selector");
    }
    subselects.push(tokens);
  }
  stripWhitespace(0);
  if (selector.length === selectorIndex) {
    return selectorIndex;
  }
  loop:
    while (selectorIndex < selector.length) {
      const firstChar = selector.charCodeAt(selectorIndex);
      switch (firstChar) {
        case CharCode.Space:
        case CharCode.Tab:
        case CharCode.NewLine:
        case CharCode.FormFeed:
        case CharCode.CarriageReturn: {
          if (tokens.length === 0 || tokens[0].type !== SelectorType.Descendant) {
            ensureNotTraversal();
            tokens.push({ type: SelectorType.Descendant });
          }
          stripWhitespace(1);
          break;
        }
        case CharCode.GreaterThan: {
          addTraversal(SelectorType.Child);
          stripWhitespace(1);
          break;
        }
        case CharCode.LessThan: {
          addTraversal(SelectorType.Parent);
          stripWhitespace(1);
          break;
        }
        case CharCode.Tilde: {
          addTraversal(SelectorType.Sibling);
          stripWhitespace(1);
          break;
        }
        case CharCode.Plus: {
          addTraversal(SelectorType.Adjacent);
          stripWhitespace(1);
          break;
        }
        case CharCode.Period: {
          addSpecialAttribute("class", AttributeAction.Element);
          break;
        }
        case CharCode.Hash: {
          addSpecialAttribute("id", AttributeAction.Equals);
          break;
        }
        case CharCode.LeftSquareBracket: {
          stripWhitespace(1);
          let name;
          let namespace = null;
          if (selector.charCodeAt(selectorIndex) === CharCode.Pipe) {
            name = getName2(1);
          } else if (selector.startsWith("*|", selectorIndex)) {
            namespace = "*";
            name = getName2(2);
          } else {
            name = getName2(0);
            if (selector.charCodeAt(selectorIndex) === CharCode.Pipe && selector.charCodeAt(selectorIndex + 1) !== CharCode.Equal) {
              namespace = name;
              name = getName2(1);
            }
          }
          stripWhitespace(0);
          let action = AttributeAction.Exists;
          const possibleAction = actionTypes.get(selector.charCodeAt(selectorIndex));
          if (possibleAction) {
            action = possibleAction;
            if (selector.charCodeAt(selectorIndex + 1) !== CharCode.Equal) {
              throw new Error("Expected `=`");
            }
            stripWhitespace(2);
          } else if (selector.charCodeAt(selectorIndex) === CharCode.Equal) {
            action = AttributeAction.Equals;
            stripWhitespace(1);
          }
          let value = "";
          let ignoreCase = null;
          if (action !== "exists") {
            if (isQuote(selector.charCodeAt(selectorIndex))) {
              const quote = selector.charCodeAt(selectorIndex);
              selectorIndex += 1;
              const sectionStart = selectorIndex;
              while (selectorIndex < selector.length && selector.charCodeAt(selectorIndex) !== quote) {
                selectorIndex += selector.charCodeAt(selectorIndex) === CharCode.BackSlash ? 2 : 1;
              }
              if (selector.charCodeAt(selectorIndex) !== quote) {
                throw new Error("Attribute value didn't end");
              }
              value = unescapeCSS(selector.slice(sectionStart, selectorIndex));
              selectorIndex += 1;
            } else {
              const valueStart = selectorIndex;
              while (selectorIndex < selector.length && !isWhitespace2(selector.charCodeAt(selectorIndex)) && selector.charCodeAt(selectorIndex) !== CharCode.RightSquareBracket) {
                selectorIndex += selector.charCodeAt(selectorIndex) === CharCode.BackSlash ? 2 : 1;
              }
              value = unescapeCSS(selector.slice(valueStart, selectorIndex));
            }
            stripWhitespace(0);
            switch (selector.charCodeAt(selectorIndex) | 32) {
              case CharCode.LowerI: {
                ignoreCase = true;
                stripWhitespace(1);
                break;
              }
              case CharCode.LowerS: {
                ignoreCase = false;
                stripWhitespace(1);
                break;
              }
            }
          }
          if (selector.charCodeAt(selectorIndex) !== CharCode.RightSquareBracket) {
            throw new Error("Attribute selector didn't terminate");
          }
          selectorIndex += 1;
          const attributeSelector = {
            type: SelectorType.Attribute,
            name,
            action,
            value,
            namespace,
            ignoreCase
          };
          tokens.push(attributeSelector);
          break;
        }
        case CharCode.Colon: {
          if (selector.charCodeAt(selectorIndex + 1) === CharCode.Colon) {
            tokens.push({
              type: SelectorType.PseudoElement,
              name: getName2(2).toLowerCase(),
              data: selector.charCodeAt(selectorIndex) === CharCode.LeftParenthesis ? readValueWithParenthesis() : null
            });
            break;
          }
          const name = getName2(1).toLowerCase();
          if (pseudosToPseudoElements.has(name)) {
            tokens.push({
              type: SelectorType.PseudoElement,
              name,
              data: null
            });
            break;
          }
          let data = null;
          if (selector.charCodeAt(selectorIndex) === CharCode.LeftParenthesis) {
            if (unpackPseudos.has(name)) {
              if (isQuote(selector.charCodeAt(selectorIndex + 1))) {
                throw new Error(`Pseudo-selector ${name} cannot be quoted`);
              }
              data = [];
              selectorIndex = parseSelector(data, selector, selectorIndex + 1);
              if (selector.charCodeAt(selectorIndex) !== CharCode.RightParenthesis) {
                throw new Error(`Missing closing parenthesis in :${name} (${selector})`);
              }
              selectorIndex += 1;
            } else {
              data = readValueWithParenthesis();
              if (stripQuotesFromPseudos.has(name)) {
                const quot = data.charCodeAt(0);
                if (quot === data.charCodeAt(data.length - 1) && isQuote(quot)) {
                  data = data.slice(1, -1);
                }
              }
              data = unescapeCSS(data);
            }
          }
          tokens.push({ type: SelectorType.Pseudo, name, data });
          break;
        }
        case CharCode.Comma: {
          finalizeSubselector();
          tokens = [];
          stripWhitespace(1);
          break;
        }
        default: {
          if (selector.startsWith("/*", selectorIndex)) {
            const endIndex = selector.indexOf("*/", selectorIndex + 2);
            if (endIndex === -1) {
              throw new Error("Comment was not terminated");
            }
            selectorIndex = endIndex + 2;
            if (tokens.length === 0) {
              stripWhitespace(0);
            }
            break;
          }
          let namespace = null;
          let name;
          if (firstChar === CharCode.Asterisk) {
            selectorIndex += 1;
            name = "*";
          } else if (firstChar === CharCode.Pipe) {
            name = "";
            if (selector.charCodeAt(selectorIndex + 1) === CharCode.Pipe) {
              addTraversal(SelectorType.ColumnCombinator);
              stripWhitespace(2);
              break;
            }
          } else if (reName.test(selector.slice(selectorIndex))) {
            name = getName2(0);
          } else {
            break loop;
          }
          if (selector.charCodeAt(selectorIndex) === CharCode.Pipe && selector.charCodeAt(selectorIndex + 1) !== CharCode.Pipe) {
            namespace = name;
            if (selector.charCodeAt(selectorIndex + 1) === CharCode.Asterisk) {
              name = "*";
              selectorIndex += 2;
            } else {
              name = getName2(1);
            }
          }
          tokens.push(name === "*" ? { type: SelectorType.Universal, namespace } : { type: SelectorType.Tag, name, namespace });
        }
      }
    }
  finalizeSubselector();
  return selectorIndex;
}
// ../imp-pinned/node_modules/css-select/dist/attributes.js
var reChars = /[-[\]{}()*+?.,\\^$|#\s]/g;
var whitespaceRe = /\s/;
function escapeRegex(value) {
  return value.replace(reChars, "\\$&");
}
var caseInsensitiveAttributes = new Set([
  "accept",
  "accept-charset",
  "align",
  "alink",
  "axis",
  "bgcolor",
  "charset",
  "checked",
  "clear",
  "codetype",
  "color",
  "compact",
  "declare",
  "defer",
  "dir",
  "direction",
  "disabled",
  "enctype",
  "face",
  "frame",
  "hreflang",
  "http-equiv",
  "lang",
  "language",
  "link",
  "media",
  "method",
  "multiple",
  "nohref",
  "noresize",
  "noshade",
  "nowrap",
  "readonly",
  "rel",
  "rev",
  "rules",
  "scope",
  "scrolling",
  "selected",
  "shape",
  "target",
  "text",
  "type",
  "valign",
  "valuetype",
  "vlink"
]);
function shouldIgnoreCase(selector, options) {
  return typeof selector.ignoreCase === "boolean" ? selector.ignoreCase : selector.ignoreCase === "quirks" ? !!options.quirksMode : !options.xmlMode && caseInsensitiveAttributes.has(selector.name);
}
var attributeRules = {
  equals(next, data, options) {
    const { adapter } = options;
    const { name } = data;
    let { value } = data;
    if (shouldIgnoreCase(data, options)) {
      value = value.toLowerCase();
      return (element) => {
        const attribute = adapter.getAttributeValue(element, name);
        return attribute != null && attribute.length === value.length && attribute.toLowerCase() === value && next(element);
      };
    }
    return (element) => adapter.getAttributeValue(element, name) === value && next(element);
  },
  hyphen(next, data, options) {
    const { adapter } = options;
    const { name } = data;
    let { value } = data;
    const { length } = value;
    if (shouldIgnoreCase(data, options)) {
      value = value.toLowerCase();
      return function hyphenIC(element) {
        const attribute = adapter.getAttributeValue(element, name);
        return attribute != null && (attribute.length === length || attribute.charAt(length) === "-") && attribute.substr(0, length).toLowerCase() === value && next(element);
      };
    }
    return function hyphen(element) {
      const attribute = adapter.getAttributeValue(element, name);
      return attribute != null && (attribute.length === length || attribute.charAt(length) === "-") && attribute.substr(0, length) === value && next(element);
    };
  },
  element(next, data, options) {
    const { adapter } = options;
    const { name, value } = data;
    if (whitespaceRe.test(value)) {
      return falseFunc;
    }
    const regex = new RegExp(`(?:^|\\s)${escapeRegex(value)}(?:$|\\s)`, shouldIgnoreCase(data, options) ? "i" : "");
    return function element(node2) {
      const attribute = adapter.getAttributeValue(node2, name);
      return attribute != null && attribute.length >= value.length && regex.test(attribute) && next(node2);
    };
  },
  exists(next, { name }, { adapter }) {
    return (element) => adapter.hasAttrib(element, name) && next(element);
  },
  start(next, data, options) {
    const { adapter } = options;
    const { name } = data;
    let { value } = data;
    const { length } = value;
    if (length === 0) {
      return falseFunc;
    }
    if (shouldIgnoreCase(data, options)) {
      value = value.toLowerCase();
      return (element) => {
        const attribute = adapter.getAttributeValue(element, name);
        return attribute != null && attribute.length >= length && attribute.substr(0, length).toLowerCase() === value && next(element);
      };
    }
    return (element) => !!adapter.getAttributeValue(element, name)?.startsWith(value) && next(element);
  },
  end(next, data, options) {
    const { adapter } = options;
    const { name } = data;
    let { value } = data;
    const length = -value.length;
    if (length === 0) {
      return falseFunc;
    }
    if (shouldIgnoreCase(data, options)) {
      value = value.toLowerCase();
      return (element) => adapter.getAttributeValue(element, name)?.substr(length).toLowerCase() === value && next(element);
    }
    return (element) => !!adapter.getAttributeValue(element, name)?.endsWith(value) && next(element);
  },
  any(next, data, options) {
    const { adapter } = options;
    const { name, value } = data;
    if (value === "") {
      return falseFunc;
    }
    if (shouldIgnoreCase(data, options)) {
      const regex = new RegExp(escapeRegex(value), "i");
      return function anyIC(element) {
        const attribute = adapter.getAttributeValue(element, name);
        return attribute != null && attribute.length >= value.length && regex.test(attribute) && next(element);
      };
    }
    return (element) => !!adapter.getAttributeValue(element, name)?.includes(value) && next(element);
  },
  not(next, data, options) {
    const { adapter } = options;
    const { name } = data;
    let { value } = data;
    if (value === "") {
      return (element) => !!adapter.getAttributeValue(element, name) && next(element);
    }
    if (shouldIgnoreCase(data, options)) {
      value = value.toLowerCase();
      return (element) => {
        const attribute = adapter.getAttributeValue(element, name);
        return (attribute == null || attribute.length !== value.length || attribute.toLowerCase() !== value) && next(element);
      };
    }
    return (element) => adapter.getAttributeValue(element, name) !== value && next(element);
  }
};

// ../imp-pinned/node_modules/css-select/dist/helpers/querying.js
function findAll2(query, nodes, options) {
  const { adapter, xmlMode = false } = options;
  const result = [];
  const nodeStack = [nodes];
  const indexStack = [0];
  for (;; ) {
    if (indexStack[0] >= nodeStack[0].length) {
      if (nodeStack.length === 1) {
        return result;
      }
      nodeStack.shift();
      indexStack.shift();
      continue;
    }
    const element = nodeStack[0][indexStack[0]++];
    if (!adapter.isTag(element)) {
      continue;
    }
    if (query(element)) {
      result.push(element);
    }
    if (xmlMode || adapter.getName(element) !== "template") {
      const children = adapter.getChildren(element);
      if (children.length > 0) {
        nodeStack.unshift(children);
        indexStack.unshift(0);
      }
    }
  }
}
function findOne2(query, nodes, options) {
  const { adapter, xmlMode = false } = options;
  const nodeStack = [nodes];
  const indexStack = [0];
  for (;; ) {
    if (indexStack[0] >= nodeStack[0].length) {
      if (nodeStack.length === 1) {
        return null;
      }
      nodeStack.shift();
      indexStack.shift();
      continue;
    }
    const element = nodeStack[0][indexStack[0]++];
    if (!adapter.isTag(element)) {
      continue;
    }
    if (query(element)) {
      return element;
    }
    if (xmlMode || adapter.getName(element) !== "template") {
      const children = adapter.getChildren(element);
      if (children.length > 0) {
        nodeStack.unshift(children);
        indexStack.unshift(0);
      }
    }
  }
}
function getNextSiblings(element, adapter) {
  const siblings = adapter.getSiblings(element);
  if (siblings.length <= 1) {
    return [];
  }
  const elementIndex = siblings.indexOf(element);
  if (elementIndex === -1 || elementIndex === siblings.length - 1) {
    return [];
  }
  return siblings.slice(elementIndex + 1).filter(adapter.isTag);
}
function getElementParent(node2, adapter) {
  const parent = adapter.getParent(node2);
  return parent != null && adapter.isTag(parent) ? parent : null;
}

// ../imp-pinned/node_modules/css-select/dist/pseudo-selectors/aliases.js
var textControl = "input:is([type=text i],[type=search i],[type=url i],[type=tel i],[type=email i],[type=password i],[type=date i],[type=month i],[type=week i],[type=time i],[type=datetime-local i],[type=number i])";
var aliases = {
  "any-link": ":is(a, area, link)[href]",
  link: ":any-link:not(:visited)",
  disabled: `:is(
        :is(button, input, select, textarea, optgroup, option)[disabled],
        optgroup[disabled] > option,
        fieldset[disabled]:not(fieldset[disabled] legend:first-of-type *)
    )`,
  enabled: ":is(button, input, select, textarea, optgroup, option, fieldset):not(:disabled)",
  checked: ":is(:is(input[type=radio], input[type=checkbox])[checked], :selected)",
  required: ":is(input, select, textarea)[required]",
  optional: ":is(input, select, textarea):not([required])",
  "read-only": `[readonly]:is(textarea, ${textControl})`,
  "read-write": `:not([readonly]):is(textarea, ${textControl})`,
  selected: "option:is([selected], select:not([multiple]):not(:has(> option[selected])) > :first-of-type)",
  checkbox: "[type=checkbox]",
  file: "[type=file]",
  password: "[type=password]",
  radio: "[type=radio]",
  reset: "[type=reset]",
  image: "[type=image]",
  submit: "[type=submit]",
  parent: ":not(:empty)",
  header: ":is(h1, h2, h3, h4, h5, h6)",
  button: ":is(button, input[type=button])",
  input: ":is(input, textarea, select, button)",
  text: "input:is(:not([type!='']), [type=text])"
};

// ../imp-pinned/node_modules/nth-check/dist/compile.js
function compile(parsed) {
  const a = parsed[0];
  const b = parsed[1] - 1;
  if (b < 0 && a <= 0)
    return falseFunc;
  if (a === -1)
    return (index) => index <= b;
  if (a === 0)
    return (index) => index === b;
  if (a === 1)
    return b < 0 ? trueFunc : (index) => index >= b;
  const absA = Math.abs(a);
  const bModulo = (b % absA + absA) % absA;
  return a > 1 ? (index) => index >= b && index % absA === bModulo : (index) => index <= b && index % absA === bModulo;
}

// ../imp-pinned/node_modules/nth-check/dist/parse.js
var whitespace = new Set([9, 10, 12, 13, 32]);
var ZERO = 48;
var NINE = 57;
function parse2(formula) {
  formula = formula.trim().toLowerCase();
  switch (formula) {
    case "even": {
      return [2, 0];
    }
    case "odd": {
      return [2, 1];
    }
  }
  let index = 0;
  let a = 0;
  let sign = readSign();
  let number = readNumber();
  if (index < formula.length && formula.charAt(index) === "n") {
    index++;
    a = sign * (number ?? 1);
    skipWhitespace();
    if (index < formula.length) {
      sign = readSign();
      skipWhitespace();
      number = readNumber();
    } else {
      sign = number = 0;
    }
  }
  if (number === null || index < formula.length) {
    throw new Error(`n-th rule couldn't be parsed ('${formula}')`);
  }
  return [a, sign * number];
  function readSign() {
    switch (formula.charAt(index)) {
      case "-": {
        index++;
        return -1;
      }
      case "+": {
        index++;
        break;
      }
    }
    return 1;
  }
  function readNumber() {
    const start = index;
    let value = 0;
    while (index < formula.length && formula.charCodeAt(index) >= ZERO && formula.charCodeAt(index) <= NINE) {
      value = value * 10 + (formula.charCodeAt(index) - ZERO);
      index++;
    }
    return index === start ? null : value;
  }
  function skipWhitespace() {
    while (index < formula.length && whitespace.has(formula.charCodeAt(index))) {
      index++;
    }
  }
}

// ../imp-pinned/node_modules/nth-check/dist/index.js
function nthCheck(formula) {
  return compile(parse2(formula));
}

// ../imp-pinned/node_modules/css-select/dist/helpers/cache.js
function cacheParentResults(next, { adapter, cacheResults }, matches) {
  if (cacheResults === false || typeof WeakMap === "undefined") {
    return (element) => next(element) && matches(element);
  }
  const resultCache = new WeakMap;
  function addResultToCache(element) {
    const result = matches(element);
    resultCache.set(element, result);
    return result;
  }
  return function cachedMatcher(element) {
    if (!next(element)) {
      return false;
    }
    if (resultCache.has(element)) {
      return resultCache.get(element) ?? false;
    }
    let node2 = element;
    do {
      const parent = getElementParent(node2, adapter);
      if (parent === null) {
        return addResultToCache(element);
      }
      node2 = parent;
    } while (!resultCache.has(node2));
    return resultCache.get(node2) ? addResultToCache(element) : false;
  };
}

// ../imp-pinned/node_modules/css-select/dist/helpers/options.js
function copyOptions(options) {
  const { context: _, rootFunc: __, ...copied } = options;
  return copied;
}

// ../imp-pinned/node_modules/css-select/dist/pseudo-selectors/filters.js
function extendedFilter(tag, range) {
  if (range[0] !== "*" && range[0] !== tag[0])
    return false;
  let tagIndex = 1;
  for (let rangeIndex = 1;rangeIndex < range.length; rangeIndex++) {
    if (range[rangeIndex] === "*")
      continue;
    while (tagIndex < tag.length && tag[tagIndex] !== range[rangeIndex]) {
      if (tag[tagIndex++].length <= 1)
        return false;
    }
    if (tagIndex >= tag.length)
      return false;
    tagIndex++;
  }
  return true;
}
var nthOfRegex = /^(.+?)\s+of\s+(.+)$/is;
function compileNth(reverse, ofType) {
  return function nth(next, rule, options, context, compileToken) {
    const { adapter, equals } = options;
    const ofMatch = ofType ? null : rule.match(nthOfRegex);
    const nthCheck2 = nthCheck(ofMatch ? ofMatch[1].trim() : rule);
    if (nthCheck2 === falseFunc)
      return falseFunc;
    const ofSelector = ofMatch && compileToken ? compileToken(parse(ofMatch[2].trim()), copyOptions(options), context) : undefined;
    if (ofSelector === falseFunc)
      return falseFunc;
    if (nthCheck2 === trueFunc && !ofSelector) {
      return (element) => getElementParent(element, adapter) !== null && next(element);
    }
    const shouldCount = ofSelector ? (_element, sibling) => ofSelector(sibling) : ofType ? (element, sibling) => adapter.getName(sibling) === adapter.getName(element) : trueFunc;
    if (reverse) {
      return function nthLast(element) {
        if (ofSelector && !ofSelector(element))
          return false;
        const siblings = adapter.getSiblings(element);
        let pos = 0;
        for (let index = siblings.length - 1;index >= 0; index--) {
          const sibling = siblings[index];
          if (equals(element, sibling))
            break;
          if (adapter.isTag(sibling) && shouldCount(element, sibling))
            pos++;
        }
        return nthCheck2(pos) && next(element);
      };
    }
    return function nth2(element) {
      if (ofSelector && !ofSelector(element))
        return false;
      const siblings = adapter.getSiblings(element);
      let pos = 0;
      for (const sibling of siblings) {
        if (equals(element, sibling))
          break;
        if (adapter.isTag(sibling) && shouldCount(element, sibling))
          pos++;
      }
      return nthCheck2(pos) && next(element);
    };
  };
}
var filters = {
  contains(next, text, options) {
    const { getText: getText2 } = options.adapter;
    return cacheParentResults(next, options, (element) => getText2(element).includes(text));
  },
  icontains(next, text, options) {
    const itext = text.toLowerCase();
    const { getText: getText2 } = options.adapter;
    return cacheParentResults(next, options, (element) => getText2(element).toLowerCase().includes(itext));
  },
  "nth-child": compileNth(false, false),
  "nth-last-child": compileNth(true, false),
  "nth-of-type": compileNth(false, true),
  "nth-last-of-type": compileNth(true, true),
  root(next, _rule, { adapter }) {
    return (element) => getElementParent(element, adapter) === null && next(element);
  },
  scope(next, rule, options, context) {
    const { equals } = options;
    if (!context || context.length === 0) {
      return filters["root"](next, rule, options);
    }
    if (context.length === 1) {
      return (element) => equals(context[0], element) && next(element);
    }
    return (element) => context.includes(element) && next(element);
  },
  lang(next, code, { adapter }) {
    const ranges = code.split(",").map((r) => r.trim()).filter((r) => r.length > 0).map((r) => r.replace(/^['"]|['"]$/g, "").toLowerCase().split("-"));
    return function lang(element) {
      let node2 = element;
      while (node2 != null) {
        const value = adapter.getAttributeValue(node2, "xml:lang") ?? adapter.getAttributeValue(node2, "lang");
        if (value != null) {
          if (!value) {
            return ranges.some((r) => r[0] === "") && next(element);
          }
          const tag = value.toLowerCase().split("-");
          return ranges.some((r) => extendedFilter(tag, r)) && next(element);
        }
        const parent = adapter.getParent(node2);
        node2 = parent != null && adapter.isTag(parent) ? parent : null;
      }
      return ranges.some((r) => r[0] === "") && next(element);
    };
  },
  hover: dynamicStatePseudo("isHovered"),
  visited: dynamicStatePseudo("isVisited"),
  active: dynamicStatePseudo("isActive")
};
function dynamicStatePseudo(name) {
  return function dynamicPseudo(next, _rule, { adapter }) {
    const filterFunction = adapter[name];
    if (typeof filterFunction !== "function") {
      return falseFunc;
    }
    return function active(element) {
      return filterFunction(element) && next(element);
    };
  };
}

// ../imp-pinned/node_modules/css-select/dist/pseudo-selectors/pseudos.js
var isDocumentWhiteSpace = /^[ \t\r\n]*$/;
var pseudos = {
  empty(element, { adapter }) {
    const children = adapter.getChildren(element);
    return children.every((element2) => !adapter.isTag(element2)) && children.every((element2) => isDocumentWhiteSpace.test(adapter.getText(element2)));
  },
  "first-child"(element, { adapter, equals }) {
    if (adapter.prevElementSibling) {
      return adapter.prevElementSibling(element) == null;
    }
    const firstChild = adapter.getSiblings(element).find((sibling) => adapter.isTag(sibling));
    return firstChild != null && equals(element, firstChild);
  },
  "last-child"(element, { adapter, equals }) {
    const siblings = adapter.getSiblings(element);
    for (let index = siblings.length - 1;index >= 0; index--) {
      if (equals(element, siblings[index])) {
        return true;
      }
      if (adapter.isTag(siblings[index])) {
        break;
      }
    }
    return false;
  },
  "first-of-type"(element, { adapter, equals }) {
    const siblings = adapter.getSiblings(element);
    const elementName = adapter.getName(element);
    for (const currentSibling of siblings) {
      if (equals(element, currentSibling)) {
        return true;
      }
      if (adapter.isTag(currentSibling) && adapter.getName(currentSibling) === elementName) {
        break;
      }
    }
    return false;
  },
  "last-of-type"(element, { adapter, equals }) {
    const siblings = adapter.getSiblings(element);
    const elementName = adapter.getName(element);
    for (let index = siblings.length - 1;index >= 0; index--) {
      const currentSibling = siblings[index];
      if (equals(element, currentSibling)) {
        return true;
      }
      if (adapter.isTag(currentSibling) && adapter.getName(currentSibling) === elementName) {
        break;
      }
    }
    return false;
  },
  "only-of-type"(element, { adapter, equals }) {
    const elementName = adapter.getName(element);
    return adapter.getSiblings(element).every((sibling) => equals(element, sibling) || !adapter.isTag(sibling) || adapter.getName(sibling) !== elementName);
  },
  "only-child"(element, { adapter, equals }) {
    return adapter.getSiblings(element).every((sibling) => equals(element, sibling) || !adapter.isTag(sibling));
  }
};
function verifyPseudoArguments(pseudoClassCondition, name, subselect, argumentIndex) {
  if (subselect === null) {
    if (pseudoClassCondition.length > argumentIndex) {
      throw new Error(`Pseudo-class :${name} requires an argument`);
    }
  } else if (pseudoClassCondition.length === argumentIndex) {
    throw new Error(`Pseudo-class :${name} doesn't have any arguments`);
  }
}

// ../imp-pinned/node_modules/css-select/dist/helpers/selectors.js
function isTraversal2(token) {
  return token.type === "_flexibleDescendant" || isTraversal(token);
}
function sortRules(array) {
  const ratings = array.map(getQuality);
  for (let index = 1;index < array.length; index++) {
    const procNew = ratings[index];
    if (procNew < 0) {
      continue;
    }
    for (let currentIndex = index;currentIndex > 0 && procNew < ratings[currentIndex - 1]; currentIndex--) {
      const token = array[currentIndex];
      array[currentIndex] = array[currentIndex - 1];
      array[currentIndex - 1] = token;
      ratings[currentIndex] = ratings[currentIndex - 1];
      ratings[currentIndex - 1] = procNew;
    }
  }
}
function getAttributeQuality(token) {
  switch (token.action) {
    case AttributeAction.Exists: {
      return 10;
    }
    case AttributeAction.Equals: {
      return token.name === "id" ? 9 : 8;
    }
    case AttributeAction.Not: {
      return 7;
    }
    case AttributeAction.Start: {
      return 6;
    }
    case AttributeAction.End: {
      return 6;
    }
    case AttributeAction.Any: {
      return 5;
    }
    case AttributeAction.Hyphen: {
      return 4;
    }
    case AttributeAction.Element: {
      return 3;
    }
  }
}
function getQuality(token) {
  switch (token.type) {
    case SelectorType.Universal: {
      return 50;
    }
    case SelectorType.Tag: {
      return 30;
    }
    case SelectorType.Attribute: {
      return Math.floor(getAttributeQuality(token) / (token.ignoreCase ? 2 : 1));
    }
    case SelectorType.Pseudo: {
      return token.data ? token.name === "has" || token.name === "contains" || token.name === "icontains" ? 0 : Array.isArray(token.data) ? Math.max(0, Math.min(...token.data.map((d) => Math.min(...d.map(getQuality))))) : 2 : 3;
    }
    default: {
      return -1;
    }
  }
}
function includesScopePseudo(t) {
  return t.type === SelectorType.Pseudo && (t.name === "scope" || Array.isArray(t.data) && t.data.some((data) => data.some(includesScopePseudo)));
}

// ../imp-pinned/node_modules/css-select/dist/pseudo-selectors/subselects.js
var PLACEHOLDER_ELEMENT = {};
function hasDependsOnCurrentElement(selector) {
  return selector.some((sel) => sel.length > 0 && (isTraversal2(sel[0]) || sel.some(includesScopePseudo)));
}
var is = (next, token, options, context, compileToken) => {
  const compiledToken = compileToken(token, copyOptions(options), context);
  return compiledToken === trueFunc ? next : compiledToken === falseFunc ? falseFunc : (element) => compiledToken(element) && next(element);
};
var subselects = {
  is,
  matches: is,
  where: is,
  not(next, token, options, context, compileToken) {
    const compiledToken = compileToken(token, copyOptions(options), context);
    return compiledToken === falseFunc ? next : compiledToken === trueFunc ? falseFunc : (element) => !compiledToken(element) && next(element);
  },
  has(next, subselect, options, _context, compileToken) {
    const { adapter } = options;
    const copiedOptions = copyOptions(options);
    copiedOptions.relativeSelector = true;
    const context = subselect.some((s) => s.some(isTraversal2)) ? [PLACEHOLDER_ELEMENT] : undefined;
    const skipCache = hasDependsOnCurrentElement(subselect);
    const compiled = compileToken(subselect, copiedOptions, context);
    if (compiled === falseFunc) {
      return falseFunc;
    }
    if (context && compiled !== trueFunc) {
      return skipCache ? (element) => {
        if (!next(element)) {
          return false;
        }
        context[0] = element;
        const childs = adapter.getChildren(element);
        return findOne2(compiled, compiled.shouldTestNextSiblings ? [
          ...childs,
          ...getNextSiblings(element, adapter)
        ] : childs, options) !== null;
      } : cacheParentResults(next, options, (element) => {
        context[0] = element;
        return findOne2(compiled, adapter.getChildren(element), options) !== null;
      });
    }
    const hasOne = (element) => findOne2(compiled, adapter.getChildren(element), options) !== null;
    return skipCache ? (element) => next(element) && hasOne(element) : cacheParentResults(next, options, hasOne);
  }
};

// ../imp-pinned/node_modules/css-select/dist/pseudo-selectors/index.js
function compilePseudoSelector(next, selector, options, context, compileToken) {
  const { name, data } = selector;
  if (Array.isArray(data)) {
    if (!(name in subselects)) {
      throw new Error(`Unknown pseudo-class :${name}(${data})`);
    }
    return subselects[name](next, data, options, context, compileToken);
  }
  const userPseudo = options.pseudos?.[name];
  const stringPseudo = typeof userPseudo === "string" ? userPseudo : aliases[name];
  if (typeof stringPseudo === "string") {
    if (data != null) {
      throw new Error(`Pseudo ${name} doesn't have any arguments`);
    }
    const alias = parse(stringPseudo);
    return subselects["is"](next, alias, options, context, compileToken);
  }
  if (typeof userPseudo === "function") {
    verifyPseudoArguments(userPseudo, name, data, 1);
    return (element) => userPseudo(element, data) && next(element);
  }
  if (name in filters) {
    return filters[name](next, data, options, context, compileToken);
  }
  if (name in pseudos) {
    const pseudo = pseudos[name];
    verifyPseudoArguments(pseudo, name, data, 2);
    return (element) => pseudo(element, options, data) && next(element);
  }
  throw new Error(`Unknown pseudo-class :${name}`);
}

// ../imp-pinned/node_modules/css-select/dist/general.js
function compileGeneralSelector(next, selector, options, context, compileToken, hasExpensiveSubselector) {
  const { adapter, equals, cacheResults } = options;
  switch (selector.type) {
    case SelectorType.PseudoElement: {
      throw new Error("Pseudo-elements are not supported by css-select");
    }
    case SelectorType.ColumnCombinator: {
      throw new Error("Column combinators are not yet supported by css-select");
    }
    case SelectorType.Attribute: {
      if (selector.namespace != null) {
        throw new Error("Namespaced attributes are not yet supported by css-select");
      }
      if (!options.xmlMode || options.lowerCaseAttributeNames) {
        selector.name = selector.name.toLowerCase();
      }
      return attributeRules[selector.action](next, selector, options);
    }
    case SelectorType.Pseudo: {
      return compilePseudoSelector(next, selector, options, context, compileToken);
    }
    case SelectorType.Tag: {
      if (selector.namespace != null) {
        throw new Error("Namespaced tag names are not yet supported by css-select");
      }
      let { name } = selector;
      if (!options.xmlMode || options.lowerCaseTags) {
        name = name.toLowerCase();
      }
      return function tag(element) {
        return adapter.getName(element) === name && next(element);
      };
    }
    case SelectorType.Descendant: {
      if (!hasExpensiveSubselector || cacheResults === false || typeof WeakMap === "undefined") {
        return function descendant(element) {
          let current = element;
          while (current = getElementParent(current, adapter)) {
            if (next(current)) {
              return true;
            }
          }
          return false;
        };
      }
      const resultCache = new WeakMap;
      return function cachedDescendant(element) {
        let current = element;
        let result;
        while (current = getElementParent(current, adapter)) {
          const cached = resultCache.get(current);
          if (cached === undefined) {
            result ??= { matches: false };
            result.matches = next(current);
            resultCache.set(current, result);
            if (result.matches) {
              return true;
            }
          } else {
            if (result) {
              result.matches = cached.matches;
            }
            return cached.matches;
          }
        }
        return false;
      };
    }
    case "_flexibleDescendant": {
      return function flexibleDescendant(element) {
        let current = element;
        do {
          if (next(current)) {
            return true;
          }
          current = getElementParent(current, adapter);
        } while (current);
        return false;
      };
    }
    case SelectorType.Parent: {
      return function parent(element) {
        return adapter.getChildren(element).some((element2) => adapter.isTag(element2) && next(element2));
      };
    }
    case SelectorType.Child: {
      return function child(element) {
        const parent = getElementParent(element, adapter);
        return parent !== null && next(parent);
      };
    }
    case SelectorType.Sibling: {
      return function sibling(element) {
        const siblings = adapter.getSiblings(element);
        for (const currentSibling of siblings) {
          if (equals(element, currentSibling)) {
            break;
          }
          if (adapter.isTag(currentSibling) && next(currentSibling)) {
            return true;
          }
        }
        return false;
      };
    }
    case SelectorType.Adjacent: {
      if (adapter.prevElementSibling) {
        return function adjacent(element) {
          const previous = adapter.prevElementSibling(element);
          return previous != null && next(previous);
        };
      }
      return function adjacent(element) {
        const siblings = adapter.getSiblings(element);
        let lastElement;
        for (const currentSibling of siblings) {
          if (equals(element, currentSibling)) {
            break;
          }
          if (adapter.isTag(currentSibling)) {
            lastElement = currentSibling;
          }
        }
        return !!lastElement && next(lastElement);
      };
    }
    case SelectorType.Universal: {
      if (selector.namespace != null && selector.namespace !== "*") {
        throw new Error("Namespaced universal selectors are not yet supported by css-select");
      }
      return next;
    }
  }
}

// ../imp-pinned/node_modules/css-select/dist/compile.js
var DESCENDANT_TOKEN = { type: SelectorType.Descendant };
var FLEXIBLE_DESCENDANT_TOKEN = {
  type: "_flexibleDescendant"
};
var SCOPE_TOKEN = {
  type: SelectorType.Pseudo,
  name: "scope",
  data: null
};
function absolutize(token, { adapter }, context) {
  const hasContext = !!context?.every((element) => element === PLACEHOLDER_ELEMENT || adapter.isTag(element) && getElementParent(element, adapter) !== null);
  for (const t of token) {
    if (t.length > 0 && isTraversal2(t[0]) && t[0].type !== SelectorType.Descendant) {} else if (hasContext && !t.some(includesScopePseudo)) {
      t.unshift(DESCENDANT_TOKEN);
    } else {
      continue;
    }
    t.unshift(SCOPE_TOKEN);
  }
}
function compileToken(token, options, compilationContext) {
  for (const rules of token) {
    sortRules(rules);
  }
  const { context = compilationContext, rootFunc: rootFunction = trueFunc } = options;
  const isArrayContext = Array.isArray(context);
  const finalContext = context && (Array.isArray(context) ? context : [context]);
  if (options.relativeSelector !== false) {
    absolutize(token, options, finalContext);
  } else if (token.some((t) => t.length > 0 && isTraversal2(t[0]))) {
    throw new Error("Relative selectors are not allowed when the `relativeSelector` option is disabled");
  }
  let shouldTestNextSiblings = false;
  let query = falseFunc;
  combineLoop:
    for (const rules of token) {
      if (rules.length >= 2) {
        const [first, second] = rules;
        if (first.type !== SelectorType.Pseudo || first.name !== "scope") {} else if (isArrayContext && second.type === SelectorType.Descendant) {
          rules[1] = FLEXIBLE_DESCENDANT_TOKEN;
        } else if (second.type === SelectorType.Adjacent || second.type === SelectorType.Sibling) {
          shouldTestNextSiblings = true;
        }
      }
      let next = rootFunction;
      let hasExpensiveSubselector = false;
      for (const rule of rules) {
        next = compileGeneralSelector(next, rule, options, finalContext, compileToken, hasExpensiveSubselector);
        const quality = getQuality(rule);
        if (quality === 0) {
          hasExpensiveSubselector = true;
        }
        if (next === falseFunc) {
          continue combineLoop;
        }
      }
      if (next === rootFunction) {
        return rootFunction;
      }
      query = query === falseFunc ? next : or(query, next);
    }
  query.shouldTestNextSiblings = shouldTestNextSiblings;
  return query;
}
function or(a, b) {
  return (element) => a(element) || b(element);
}

// ../imp-pinned/node_modules/css-select/dist/index.js
var defaultEquals = (a, b) => a === b;
var defaultOptions2 = {
  adapter: { ...exports_dist2, isTag: isTag2 },
  equals: defaultEquals
};
function convertOptionFormats(options) {
  const finalOptions = options ?? defaultOptions2;
  finalOptions.adapter ??= defaultOptions2.adapter;
  finalOptions.equals ??= finalOptions.adapter?.equals ?? defaultEquals;
  return finalOptions;
}
function compile2(selector, options, context) {
  const convertedOptions = convertOptionFormats(options);
  const next = _compileUnsafe(selector, convertedOptions, context);
  return next === falseFunc ? falseFunc : (element) => convertedOptions.adapter.isTag(element) && next(element);
}
function _compileUnsafe(selector, options, context) {
  return compileToken(typeof selector === "string" ? parse(selector) : selector, convertOptionFormats(options), context);
}
function getSelectorFunction(searchFunction) {
  return function select(query, elements, options) {
    const convertedOptions = convertOptionFormats(options);
    if (typeof query !== "function") {
      query = _compileUnsafe(query, convertedOptions, elements);
    }
    const filteredElements = prepareContext(elements, convertedOptions.adapter, query.shouldTestNextSiblings);
    return searchFunction(query, filteredElements, convertedOptions);
  };
}
function prepareContext(elements, adapter, shouldTestNextSiblings = false) {
  if (shouldTestNextSiblings) {
    elements = appendNextSiblings(elements, adapter);
  }
  return Array.isArray(elements) ? adapter.removeSubsets(elements) : adapter.getChildren(elements);
}
function appendNextSiblings(element, adapter) {
  const elements = Array.isArray(element) ? [...element] : [element];
  const elementsLength = elements.length;
  for (let index = 0;index < elementsLength; index++) {
    const nextSiblings = getNextSiblings(elements[index], adapter);
    elements.push(...nextSiblings);
  }
  return elements;
}
var selectAll = getSelectorFunction((query, elements, options) => query === falseFunc || !elements || elements.length === 0 ? [] : findAll2(query, elements, options));
var selectOne = getSelectorFunction((query, elements, options) => query === falseFunc || !elements || elements.length === 0 ? null : findOne2(query, elements, options));
function is2(element, query, options) {
  return (typeof query === "function" ? query : compile2(query, options))(element);
}
var dist_default2 = selectAll;

// entry.mjs
var import_cjs = __toESM(require_cjs(), 1);
var export_csstree = import_cjs.default;

export {
  exports_dist3 as htmlparser2,
  exports_dist2 as domutils,
  export_csstree as csstree,
  exports_dist5 as cssSelect
};
