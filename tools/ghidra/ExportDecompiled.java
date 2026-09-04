// Ghidra headless script: decompile all functions of the current program into
// an output directory (combined .c file + per-function files + symbols TSV).
//
// This is the developer tool used to extend pydwshape's offline RVA registry
// (src/pydwshape/rva_registry.json) for a new TextShaping.dll build. See
// README.md in this folder for the exact workflow.
//
// Usage (analyzeHeadless): -postScript ExportDecompiled.java "<output_dir>"
//@category Export

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Program;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.util.task.ConsoleTaskMonitor;
import ghidra.util.task.TaskMonitor;

public class ExportDecompiled extends GhidraScript {

	@Override
	protected void run() throws Exception {
		Program program = getCurrentProgram();
		if (program == null) {
			printerr("No program loaded!");
			return;
		}

		String[] args = getScriptArgs();
		String outPath = (args.length > 0) ? args[0]
				: System.getProperty("user.home") + File.separator + "ghidra_export";
		File outputDir = new File(outPath);
		outputDir.mkdirs();
		File individualDir = new File(outputDir, "functions");
		individualDir.mkdirs();

		String base = program.getName().replaceAll("\\.dll$", "");

		println("Program: " + program.getName());
		println("Language: " + program.getLanguageID());
		println("Output : " + outputDir.getAbsolutePath());

		DecompInterface decompiler = new DecompInterface();
		decompiler.openProgram(program);

		PrintWriter all = new PrintWriter(new FileWriter(new File(outputDir, base + "_all.c")));
		all.println("=".repeat(80));
		all.println("Decompilation of " + program.getName());
		all.println("Architecture: " + program.getLanguageID());
		all.println("=".repeat(80));
		all.println();

		// Symbol table dump (exports, imports, discovered functions)
		PrintWriter sym = new PrintWriter(new FileWriter(new File(outputDir, base + "_symbols.tsv")));
		sym.println("Address\tType\tName\tNamespace");
		SymbolTable symTable = program.getSymbolTable();
		for (Symbol s : symTable.getAllSymbols(true)) {
			String ns = (s.getParentNamespace() != null) ? s.getParentNamespace().getName() : "";
			sym.println(s.getAddress() + "\t" + s.getSymbolType() + "\t" + s.getName() + "\t" + ns);
		}
		sym.close();

		FunctionManager funcMgr = program.getFunctionManager();
		FunctionIterator functions = funcMgr.getFunctions(true);

		int total = 0, ok = 0, failed = 0;
		TaskMonitor monitor = new ConsoleTaskMonitor();

		while (functions.hasNext() && !monitor.isCancelled()) {
			Function function = functions.next();
			total++;
			String funcName = function.getName();
			String funcAddr = function.getEntryPoint().toString();

			DecompileResults res = decompiler.decompileFunction(function, 60, monitor);
			// Ghidra 12.x: use getDecompiledFunction() (not .decompiledFunction)
			if (res != null && res.getDecompiledFunction() != null) {
				try {
					String cCode = res.getDecompiledFunction().getC();
					ok++;

					all.println("-".repeat(80));
					all.println("Function: " + funcName);
					all.println("Address: " + funcAddr);
					all.println("Signature: " + function.getSignature(false));
					all.println();
					all.println(cCode);
					all.println();

					if (cCode.length() > 300) {
						String safeName = funcName.replaceAll("[^A-Za-z0-9_.-]", "_");
						if (safeName.length() > 120) safeName = safeName.substring(0, 120);
						PrintWriter w = new PrintWriter(new FileWriter(
								new File(individualDir, funcAddr + "_" + safeName + ".c")));
						w.println("// Function: " + funcName);
						w.println("// Address: " + funcAddr);
						w.println("// Signature: " + function.getSignature(false));
						w.println();
						w.println(cCode);
						w.close();
					}
				} catch (Exception e) {
					failed++;
				}
			} else {
				failed++;
			}

			if (total % 500 == 0) {
				println("Processed " + total + " functions...");
			}
		}

		decompiler.dispose();
		all.close();

		println("=".repeat(60));
		println("Total functions: " + total + "  decompiled ok: " + ok + "  failed: " + failed);
		println("Output written to " + outputDir.getAbsolutePath());
		println("=".repeat(60));
	}
}
