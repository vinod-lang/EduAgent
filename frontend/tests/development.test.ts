import {it,expect} from "vitest";
import {developmentLoginEnabled,developmentAliases} from "@/lib/development";
it("requires all explicit development flags",()=>{expect(developmentLoginEnabled({NODE_ENV:"development",EDUAGENT_FRONTEND_MODE:"development",EDUAGENT_FRONTEND_DEV_AUTH:"true"})).toBe(true);expect(developmentLoginEnabled({NODE_ENV:"development"})).toBe(false);});
it("refuses dev login in production even if flags are set",()=>{expect(developmentLoginEnabled({NODE_ENV:"production",EDUAGENT_FRONTEND_MODE:"development",EDUAGENT_FRONTEND_DEV_AUTH:"true"})).toBe(false);});
it("only provides configured safe aliases",()=>{expect(developmentAliases({NODE_ENV:"development",EDUAGENT_DEV_ALIASES:"professor-a, professor-b"})).toEqual(["professor-a","professor-b"]);});
